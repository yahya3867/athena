import json
import re

import requests

import config
from image_intent import extract_image_prompt


_ROUTER_PROMPT = (
    "You are an intent router for Athena, a voice assistant. "
    "Classify whether the user's request is asking Athena to create or display an image or visual aid, "
    "or whether it is a normal chat/explanation/search request. "
    "You may use recent conversation history to resolve pronouns like him, her, them, it, this, or that into a specific subject when possible. "
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
_PROMPTS_NEEDING_CONTEXT = {
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "they",
    "them",
    "their",
    "theirs",
    "it",
    "its",
    "this",
    "that",
    "these",
    "those",
}
_DISPLAYED_IMAGE_RE = re.compile(r"^displayed an image of (?P<subject>.+?)[.?!]*$", re.IGNORECASE)
_QUESTION_SUBJECT_RE = re.compile(
    r"^(?:who is|who's|what is|what's|tell me about)\s+(?P<subject>.+?)(?:\?|$)",
    re.IGNORECASE,
)
_VISUAL_SUBJECT_RE = re.compile(
    r"^(?:show me|give me|can i have|generate|create|make|draw|paint)\b.*?\bof\s+(?P<subject>.+?)(?:\?|$)",
    re.IGNORECASE,
)
_ASSISTANT_NAME_RE = re.compile(
    r"\b(?:is|was|are|were)\s+(?P<subject>[A-Z][A-Za-z'’.-]*(?:\s+[A-Z][A-Za-z'’.-]*){0,5})(?:[,.!?]|$)"
)
_LEADING_NAME_RE = re.compile(
    r"^(?P<subject>[A-Z][A-Za-z'’.-]*(?:\s+[A-Z][A-Za-z'’.-]*){0,5})(?:\s+(?:is|was|are|were)\b|[,.!?]|$)"
)
_TRAILING_CONTEXT_RE = re.compile(
    r"\b(?:please|right now|currently|today|now|for me|for us)\b",
    re.IGNORECASE,
)
_TRAILING_PUNCT_RE = re.compile(r"[\s,.;:!?]+$")


def route_user_request(
    user_text: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, str | None]:
    fallback_prompt = _resolve_prompt_with_history(extract_image_prompt(user_text), history)
    fallback = {
        "mode": "image" if fallback_prompt else "chat",
        "image_prompt": fallback_prompt,
    }

    if not config.OPENAI_API_KEY:
        return fallback

    try:
        routed = _route_with_model(user_text, history)
    except Exception:
        return fallback

    if routed.get("mode") == "image":
        routed = {
            "mode": "image",
            "image_prompt": _resolve_prompt_with_history(routed.get("image_prompt"), history),
        }

    if _is_valid_route(routed):
        if routed.get("mode") == "chat" and fallback_prompt:
            return fallback
        return routed

    if fallback_prompt:
        return fallback
    return {"mode": "chat", "image_prompt": None}


def _route_with_model(
    user_text: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, str | None]:
    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.OPENAI_INTENT_MODEL,
        "input": _build_router_input(user_text, history),
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


def _build_router_input(
    user_text: str,
    history: list[dict[str, str]] | None = None,
) -> list[dict[str, str]]:
    inputs: list[dict[str, str]] = [{"role": "system", "content": _ROUTER_PROMPT}]
    if history:
        for message in history[-4:]:
            role = str(message.get("role", "")).strip()
            content = str(message.get("content", "")).strip()
            if role in {"user", "assistant"} and content:
                inputs.append({"role": role, "content": content})
    inputs.append({"role": "user", "content": user_text})
    return inputs


def _resolve_prompt_with_history(
    prompt: str | None,
    history: list[dict[str, str]] | None,
) -> str | None:
    if not prompt:
        return prompt
    prompt = prompt.strip()
    if not history or not _prompt_needs_context(prompt):
        return prompt
    for message in reversed(history[-6:]):
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        subject = _extract_subject_from_message(content)
        if subject and not _prompt_needs_context(subject):
            return subject
    return prompt


def _prompt_needs_context(prompt: str) -> bool:
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", prompt).strip().lower()
    if not cleaned:
        return False
    return cleaned in _PROMPTS_NEEDING_CONTEXT


def _extract_subject_from_message(content: str) -> str | None:
    for pattern in (_DISPLAYED_IMAGE_RE, _QUESTION_SUBJECT_RE, _VISUAL_SUBJECT_RE):
        match = pattern.match(content.strip())
        if match:
            subject = _normalize_subject(match.group("subject"))
            if subject:
                return subject

    for pattern in (_ASSISTANT_NAME_RE, _LEADING_NAME_RE):
        match = pattern.search(content.strip())
        if match:
            subject = _normalize_subject(match.group("subject"))
            if subject:
                return subject
    return None


def _normalize_subject(subject: str) -> str | None:
    subject = subject.strip()
    subject = _TRAILING_CONTEXT_RE.sub("", subject).strip()
    subject = _TRAILING_PUNCT_RE.sub("", subject).strip()
    if subject.lower().endswith(" like"):
        subject = subject[:-5].strip()
    return subject or None


def _is_valid_route(route: dict[str, str | None]) -> bool:
    mode = route.get("mode")
    image_prompt = route.get("image_prompt")
    if mode == "chat":
        return True
    if mode == "image" and isinstance(image_prompt, str) and image_prompt.strip():
        return True
    return False
