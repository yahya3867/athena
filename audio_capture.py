import math
import os
import shutil
import signal
import struct
import subprocess
import time
import wave
from pathlib import Path

import config


def check_audio_level(wav_path: str | Path) -> float:
    """Return RMS energy of a 16-bit WAV. 0 = silence, ~32768 = max."""
    try:
        with wave.open(str(wav_path), "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames == 0:
                return 0.0
            raw = wf.readframes(n_frames)
            n_samples = n_frames * wf.getnchannels()
            if len(raw) < n_samples * 2:
                return 0.0
            samples = struct.unpack(f"<{n_samples}h", raw[: n_samples * 2])
            return math.sqrt(sum(s * s for s in samples) / n_samples)
    except Exception as exc:
        print(f"[audio] audio level check failed: {exc}")
        return float("inf")


def create_silence_fixture(
    output_path: str | Path,
    duration_sec: float = 1.0,
    sample_rate: int | None = None,
) -> Path:
    sample_rate = sample_rate or config.AUDIO_SAMPLE_RATE
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    num_samples = max(1, int(duration_sec * sample_rate))
    silence = b"\x00\x00" * num_samples
    with wave.open(str(output), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(silence)
    return output


class Recorder:
    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._output_path: Path = config.DEFAULT_WAV_PATH

    @property
    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _ffmpeg_cmd(self, output_path: Path) -> list[str]:
        return [
            config.FFMPEG_BIN,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "avfoundation" if os.uname().sysname == "Darwin" else "alsa",
            "-i",
            config.AUDIO_INPUT_DEVICE if os.uname().sysname == "Darwin" else "default",
            "-ac",
            str(config.AUDIO_CHANNELS),
            "-ar",
            str(config.AUDIO_SAMPLE_RATE),
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]

    def start(self, output_path: str | Path | None = None) -> Path:
        if self.is_recording:
            return Path(output_path or config.DEFAULT_WAV_PATH)

        config.ensure_dirs()
        output = Path(output_path or config.DEFAULT_WAV_PATH)
        self._output_path = output
        if output.exists():
            output.unlink()

        if shutil.which(config.FFMPEG_BIN) is None:
            raise RuntimeError(
                f"{config.FFMPEG_BIN} not found. Install ffmpeg before using live microphone capture."
            )

        cmd = self._ffmpeg_cmd(output)
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            print(f"[audio] recording to {output}")
            return output
        except Exception as exc:
            raise RuntimeError(f"Unable to start recording: {exc}") from exc

    def stop(self) -> Path:
        proc = self._proc
        output = self._output_path
        if proc is None:
            return output

        try:
            proc.send_signal(signal.SIGINT)
        except OSError:
            pass

        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

        stderr = ""
        if proc.stderr:
            try:
                stderr = proc.stderr.read().decode(errors="replace").strip()
            except Exception:
                stderr = ""

        self._proc = None

        if not output.exists() or output.stat().st_size < 100:
            raise RuntimeError(
                f"Recording failed or output WAV is too small: {output}\n{stderr}".strip()
            )
        return output

    def cancel(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        self._proc = None

    def record_interactive(self, output_path: str | Path | None = None) -> Path:
        output = self.start(output_path)
        print("[audio] press Enter to stop recording")
        try:
            input()
        except KeyboardInterrupt:
            self.cancel()
            raise RuntimeError("Recording cancelled")
        final_path = self.stop()
        rms = check_audio_level(final_path)
        duration = _wav_duration_seconds(final_path)
        print(f"[audio] saved {final_path} ({duration:.2f}s, RMS={rms:.0f})")
        return final_path


def _wav_duration_seconds(wav_path: str | Path) -> float:
    with wave.open(str(wav_path), "rb") as wf:
        rate = wf.getframerate() or 1
        return wf.getnframes() / rate
