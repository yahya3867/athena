import queue
import shutil
import subprocess
import threading
import time
import wave
import logging
from pathlib import Path

import requests

import config


_SENTINEL = object()
log = logging.getLogger("athena.tts")


class TTSPlayer:
    """Simple queued TTS player that preserves the submit/flush workflow shape."""

    def __init__(self):
        self._queue: queue.Queue[str | object] = queue.Queue()
        self._done = threading.Event()
        self._cancel = threading.Event()
        self._current_text = ""
        self._play_proc: subprocess.Popen | None = None
        self._playback_start: float = 0.0
        self._playback_duration: float = 0.0
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()

    @property
    def current_text(self) -> str:
        return self._current_text

    def get_mouth_shape(self) -> int:
        if self._play_proc is None or self._play_proc.poll() is not None:
            return -1
        elapsed = time.monotonic() - self._playback_start
        if elapsed < 0.08:
            return 1
        if elapsed < max(0.2, self._playback_duration * 0.4):
            return 2
        if elapsed < self._playback_duration:
            return 1
        return -1

    def submit(self, text: str) -> None:
        text = (text or "").strip()
        if not text or not config.ENABLE_TTS:
            return
        self._queue.put(text)

    def flush(self) -> None:
        self._done.clear()
        self._queue.put(_SENTINEL)
        deadline = time.monotonic() + 120
        while not self._done.is_set():
            if self._cancel.is_set():
                self._done.set()
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._done.wait(timeout=min(0.1, remaining))

    def cancel(self) -> None:
        self._cancel.set()
        if self._play_proc and self._play_proc.poll() is None:
            try:
                self._play_proc.terminate()
            except OSError:
                pass
        self._play_proc = None
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put(_SENTINEL)
        self._current_text = ""
        self._done.set()

    def speak_once(self, text: str, output_path: str | Path | None = None) -> Path:
        output = _fetch_tts_wav(text, output_path or config.DEFAULT_TTS_WAV_PATH)
        _play_audio(output)
        return output

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is _SENTINEL:
                self._cancel.clear()
                self._current_text = ""
                self._done.set()
                continue
            if self._cancel.is_set():
                self._cancel.clear()
                self._current_text = ""
                self._done.set()
                continue
            text = str(item).strip()
            if not text:
                continue
            self._current_text = text
            try:
                output = _fetch_tts_wav(text, config.DEFAULT_TTS_WAV_PATH)
                self._playback_start = time.monotonic()
                self._playback_duration = _wav_duration_seconds(output)
                _play_audio(output, owner=self)
            except Exception as exc:
                log.warning("TTS playback failed: %s", exc)
                self._play_proc = None
                self._playback_start = 0.0
                self._playback_duration = 0.0
            finally:
                if self._cancel.is_set():
                    self._cancel.clear()
                self._current_text = ""


def _fetch_tts_wav(text: str, output_path: str | Path) -> Path:
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required for TTS.")

    url = "https://api.openai.com/v1/audio/speech"
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.OPENAI_TTS_MODEL,
        "voice": config.OPENAI_TTS_VOICE,
        "input": text,
        "response_format": "wav",
        "speed": max(0.25, min(4.0, config.OPENAI_TTS_SPEED)),
    }
    if config.OPENAI_TTS_INSTRUCTIONS:
        payload["instructions"] = config.OPENAI_TTS_INSTRUCTIONS
    try:
        resp = requests.post(url, json=payload, headers=headers, stream=True, timeout=60)
    except Exception as exc:
        raise RuntimeError(f"TTS request failed: {exc}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"TTS failed ({resp.status_code}): {resp.text[:300]}")

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=4096):
            if chunk:
                fh.write(chunk)
    _apply_gain_to_wav(output, config.OPENAI_TTS_GAIN_DB)
    return output


def _play_audio(path: str | Path, owner: TTSPlayer | None = None) -> None:
    if shutil.which(config.PLAYBACK_BIN) is None:
        raise RuntimeError(
            f"{config.PLAYBACK_BIN} not found. Set PLAYBACK_BIN in .env to a valid audio player."
        )
    cmd = [config.PLAYBACK_BIN, str(path)]
    if config.PLAYBACK_BIN.endswith("aplay") or config.PLAYBACK_BIN == "aplay":
        if owner:
            _normalize_playback_levels(owner)
        cmd = [config.PLAYBACK_BIN, "-q", "-D", config.AUDIO_OUTPUT_DEVICE, str(path)]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if owner:
        owner._play_proc = proc
    try:
        proc.wait(timeout=120)
    except subprocess.TimeoutExpired:
        proc.terminate()
        proc.wait(timeout=2)


def _wav_duration_seconds(path: str | Path) -> float:
    try:
        import wave

        with wave.open(str(path), "rb") as wf:
            rate = wf.getframerate() or 1
            return wf.getnframes() / rate
    except Exception:
        return 0.0


def _normalize_playback_levels(owner: TTSPlayer | None = None) -> None:
    controls = ("Speaker", "Speaker AC", "Speaker DC", "Playback")
    for control in controls:
        subprocess.run(
            ["amixer", "-q", "-c", "1", "sset", control, "100%"],
            capture_output=True,
            check=False,
        )


def _apply_gain_to_wav(path: str | Path, gain_db: float) -> None:
    if gain_db <= 0:
        return
    try:
        wav_path = Path(path)
        with wave.open(str(wav_path), "rb") as src:
            params = src.getparams()
            if params.sampwidth != 2:
                return
            frames = src.readframes(src.getnframes())
        if not frames:
            return

        import array
        import math

        gain = math.pow(10.0, gain_db / 20.0)
        samples = array.array("h")
        samples.frombytes(frames)
        for i, sample in enumerate(samples):
            boosted = int(sample * gain)
            if boosted > 32767:
                boosted = 32767
            elif boosted < -32768:
                boosted = -32768
            samples[i] = boosted

        with wave.open(str(wav_path), "wb") as dst:
            dst.setparams(params)
            dst.writeframes(samples.tobytes())
    except Exception:
        return
