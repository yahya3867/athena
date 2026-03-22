import json

import requests

import config
from image_intent import extract_image_prompt


_ROUTER_PROMPT = (
    "You are an intent router for Athena, a voice assistant. "
    "Classify whether the user's request is asking Athena to create or display an image or visual aid, "
    "or whether it is a normal chat/explanation/search request. "
    "Treat requests for maps, diagrams, charts, illustrations, visuals, posters, banners, signs, flyers, cards, and simple visual help as image requests. "
    "If it is an image request, rewrite it into a clean image-generation prompt that preserves style modifiers "
    "like 'make it cartoony', 'make it dramatic', or 'use warm colors'. "
    "When the request is for a map, diagram, poster, or text-in-image design, rewrite it into a simple, display-friendly visual prompt. "
    "If the user says the picture should contain words, preserve that text in the image prompt. "
    "Return JSON only with keys: mode and image_prompt. "
    "mode must be exactly 'image' or 'chat'. "
    "image_prompt must be a string for image mode, otherwise null. "
    "Do not include markdown or any extra text."
)


def route_user_request(user_text: str) -> dict[str, str | None]:
    fallback_prompt = extract_image_prompt(user_text)
    fallback = {
        "mode": "image" if fallback_prompt else "chat",
        "image_prompt": fallback_prompt,
    }

    if not config.OPENAI_API_KEY:
        return fallback

    try:
        routed = _route_with_model(user_text)
    except Exception:
        return fallback

    if _is_valid_route(routed):
        if routed.get("mode") == "chat" and fallback_prompt:
            return fallback
        return routed

    if fallback_prompt:
        return fallback
    return {"mode": "chat", "image_prompt": None}


def _route_with_model(user_text: str) -> dict[str, str | None]:
    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.OPENAI_INTENT_MODEL,
        "input": [
            {"role": "system", "content": _ROUTER_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "max_output_tokens": 120,
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=45)
    if resp.status_code != 200:
        raise RuntimeError(f"Intent routing failed ({resp.status_code}): {resp.text[:300]}")
    data = resp.json()
    text = _extract_text(data).strip()
    if not text:
        raise RuntimeError("Intent router returned empty output.")
    return _parse_route(text)


def _extract_text(data: dict) -> str:
    parts: list[str] = []
    for output in data.get("output", []):
        for content in output.get("content", []):
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "".join(parts)


def _parse_route(text: str) -> dict[str, str | None]:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise RuntimeError(f"Intent router returned non-JSON output: {text[:200]}")
    parsed = json.loads(text[start : end + 1])
    mode = parsed.get("mode")
    image_prompt = parsed.get("image_prompt")
    if isinstance(image_prompt, str):
        image_prompt = image_prompt.strip() or None
    elif image_prompt is not None:
        image_prompt = None
    return {"mode": mode, "image_prompt": image_prompt}


def _is_valid_route(route: dict[str, str | None]) -> bool:
    mode = route.get("mode")
    image_prompt = route.get("image_prompt")
    if mode == "chat":
        return True
    if mode == "image" and isinstance(image_prompt, str) and image_prompt.strip():
        return True
    return False
