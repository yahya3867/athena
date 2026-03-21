from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config


_http_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        _http_session.mount("http://", adapter)
        _http_session.mount("https://", adapter)
    return _http_session


def transcribe(wav_path: str | Path) -> str:
    """Transcribe a WAV file using OpenAI's transcription API."""
    if not config.OPENAI_API_KEY:
        print("[stt] OPENAI_API_KEY missing; type the transcript manually.")
        try:
            return input("> ").strip()
        except EOFError:
            return ""

    wav_path = Path(wav_path)
    if not wav_path.exists():
        raise FileNotFoundError(f"WAV file not found: {wav_path}")
    if wav_path.stat().st_size < 100:
        raise ValueError(f"WAV file too small ({wav_path.stat().st_size} bytes)")

    url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}

    with wav_path.open("rb") as fh:
        try:
            resp = _get_session().post(
                url,
                headers=headers,
                files={"file": (wav_path.name, fh, "audio/wav")},
                data={
                    "model": config.OPENAI_TRANSCRIBE_MODEL,
                    "response_format": "text",
                },
                timeout=60,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise RuntimeError(f"Transcription request failed: {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(f"Transcription failed ({resp.status_code}): {resp.text[:300]}")

    transcript = resp.text.strip()
    print(f"[stt] transcript: {transcript[:200]}")
    return transcript
