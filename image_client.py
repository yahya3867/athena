import base64
import time
from pathlib import Path

import requests

import config


def generate_image(prompt: str) -> str:
    prompt = (prompt or "").strip()
    if not prompt:
        raise RuntimeError("Image prompt is empty.")
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required for image generation.")

    config.ensure_dirs()

    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    image_base64 = _generate_via_responses(prompt, headers)
    if not image_base64:
        image_base64 = _generate_via_images_endpoint(prompt, headers)
    if not image_base64:
        raise RuntimeError("Image generation succeeded but returned no image payload.")

    output_path = config.IMAGE_OUTPUT_DIR / f"athena-image-{int(time.time() * 1000)}.png"
    _write_base64_image(output_path, image_base64)
    return str(output_path.resolve())


def _extract_image_base64(data: dict) -> str | None:
    for output in data.get("output", []):
        if output.get("type") == "image_generation_call" and output.get("result"):
            return output["result"]
    return None


def _generate_via_responses(prompt: str, headers: dict[str, str]) -> str | None:
    url = "https://api.openai.com/v1/responses"
    payload = {
        "model": config.OPENAI_IMAGE_MODEL,
        "input": prompt,
        "tools": [{"type": "image_generation"}],
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=180)
    except Exception as exc:
        raise RuntimeError(f"Image generation request failed: {exc}") from exc
    if resp.status_code == 200:
        return _extract_image_base64(resp.json())
    if resp.status_code not in (400, 404, 422):
        raise RuntimeError(f"Image generation failed ({resp.status_code}): {resp.text[:300]}")
    return None


def _generate_via_images_endpoint(prompt: str, headers: dict[str, str]) -> str | None:
    url = "https://api.openai.com/v1/images/generations"
    payload = {
        "model": config.OPENAI_IMAGE_MODEL,
        "prompt": prompt,
        "size": config.OPENAI_IMAGE_SIZE,
        "quality": config.OPENAI_IMAGE_QUALITY,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=180)
    except Exception as exc:
        raise RuntimeError(f"Image generation request failed: {exc}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"Image generation failed ({resp.status_code}): {resp.text[:300]}")
    data = resp.json()
    images = data.get("data", [])
    if not images:
        return None
    first = images[0]
    if first.get("b64_json"):
        return first["b64_json"]
    if first.get("url"):
        return _download_image_as_base64(first["url"])
    return None


def _write_base64_image(path: Path, image_base64: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image_bytes = base64.b64decode(image_base64)
    path.write_bytes(image_bytes)


def _download_image_as_base64(url: str) -> str:
    try:
        resp = requests.get(url, timeout=180)
    except Exception as exc:
        raise RuntimeError(f"Image download failed: {exc}") from exc
    if resp.status_code != 200:
        raise RuntimeError(f"Image download failed ({resp.status_code}): {resp.text[:300]}")
    return base64.b64encode(resp.content).decode("ascii")
