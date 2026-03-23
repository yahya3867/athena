import math
import os
import signal
import struct
import subprocess
import time
import wave
from dataclasses import dataclass

import config

WAV_PATH = "/tmp/utterance.wav"
MIN_VALID_WAV_BYTES = 100


@dataclass(frozen=True)
class RecordingResult:
    path: str
    exists: bool
    size_bytes: int
    valid: bool
    stderr: str = ""


def check_audio_level(wav_path: str) -> float:
    """Return RMS energy of a 16-bit mono WAV. 0 = silence, ~32768 = max."""
    try:
        with wave.open(wav_path, "rb") as wf:
            n_frames = wf.getnframes()
            if n_frames == 0:
                return 0.0
            raw = wf.readframes(n_frames)
            n_samples = n_frames * wf.getnchannels()
            if len(raw) < n_samples * 2:
                return 0.0
            samples = struct.unpack(f"<{n_samples}h", raw[: n_samples * 2])
            return math.sqrt(sum(s * s for s in samples) / n_samples)
    except Exception as e:
        print(f"[rec] audio level check failed: {e}")
        return float("inf")


def _dump_audio_info():
    """Print audio device info for debugging."""
    print("--- /proc/asound/cards ---")
    try:
        with open("/proc/asound/cards") as f:
            print(f.read())
    except Exception as e:
        print(f"  (unavailable: {e})")

    print("--- arecord -l ---")
    try:
        result = subprocess.run(
            ["arecord", "-l"], capture_output=True, text=True, timeout=5
        )
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
    except Exception as e:
        print(f"  (unavailable: {e})")


class Recorder:
    def __init__(self):
        self._proc: subprocess.Popen | None = None

    @property
    def is_recording(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        if self.is_recording:
            return

        self.discard()

        cmd = [
            "arecord",
            "-D", config.AUDIO_DEVICE,
            "-f", "S16_LE",
            "-r", str(config.AUDIO_SAMPLE_RATE),
            "-c", "1",
            "-t", "wav",
            WAV_PATH,
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            print(f"[rec] started: {' '.join(cmd)}")
        except FileNotFoundError:
            print("[rec] ERROR: arecord not found — install alsa-utils")
            _dump_audio_info()
            raise
        except Exception:
            _dump_audio_info()
            raise

    def stop(self, *, quiet_if_tiny: bool = False) -> RecordingResult:
        """Stop recording and report whether the capture looks valid."""
        proc = self._proc
        if proc is None:
            exists = os.path.exists(WAV_PATH)
            size_bytes = os.path.getsize(WAV_PATH) if exists else 0
            return RecordingResult(
                path=WAV_PATH,
                exists=exists,
                size_bytes=size_bytes,
                valid=exists and size_bytes >= MIN_VALID_WAV_BYTES,
            )

        # Send SIGINT for clean WAV header finalization
        try:
            proc.send_signal(signal.SIGINT)
        except OSError:
            pass

        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)

        stderr = ""
        if proc.stderr:
            try:
                stderr = proc.stderr.read().decode(errors="replace")
            except Exception:
                pass

        self._proc = None

        exists = os.path.exists(WAV_PATH)
        size_bytes = os.path.getsize(WAV_PATH) if exists else 0
        valid = exists and size_bytes >= MIN_VALID_WAV_BYTES

        if not valid and not quiet_if_tiny:
            print(f"[rec] WARNING: WAV file missing or too small")
            if stderr:
                print(f"[rec] stderr: {stderr}")
            _dump_audio_info()

        return RecordingResult(
            path=WAV_PATH,
            exists=exists,
            size_bytes=size_bytes,
            valid=valid,
            stderr=stderr,
        )

    def cancel(self) -> None:
        """Kill recording without caring about output."""
        proc = self._proc
        if proc is None:
            self.discard()
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
        self.discard()

    def discard(self) -> None:
        """Remove any leftover recording artifact from a prior turn."""
        try:
            if os.path.exists(WAV_PATH):
                os.remove(WAV_PATH)
        except OSError:
            pass
