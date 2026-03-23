import json
import re

import requests

import config
from image_intent import clean_request_text, extract_image_prompt


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
    "there",
    "that city",
    "that place",
    "that one",
    "this one",
    "that map",
    "that diagram",
    "that picture",
    "that image",
    "that poster",
    "that banner",
    "that flyer",
    "that sign",
    "that graphic",
    "that card",
    "one of that",
    "one of it",
    "one of them",
}
_DISPLAYED_IMAGE_RE = re.compile(r"^displayed an image of (?P<subject>.+?)[.?!]*$", re.IGNORECASE)
_QUESTION_SUBJECT_RE = re.compile(
    r"^(?:who is|who's|who was|what is|what's|what was|where is|where's|tell me about|explain)\s+(?P<subject>.+?)(?:\?|$)",
    re.IGNORECASE,
)
_VISUAL_SUBJECT_RE = re.compile(
    r"^(?:show me|give me|can i have|generate|create|make|draw|paint|display|pull up)\b.*?\bof\s+(?P<subject>.+?)(?:\?|$)",
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
_CONTEXTUAL_PROMPT_RE = re.compile(
    r"^(?P<context>one of that|one of it|one of them|that city|that place|that one|this one|that map|that diagram|that picture|that image|that poster|that banner|that flyer|that sign|that graphic|that card|him|her|them|these|those|there|this|that|it)(?:\s+(?P<rest>.+))?$",
    re.IGNORECASE,
)
_FOLLOWUP_REPEAT_RE = re.compile(
    r"^(?:now\s+)?(?:show|display|pull up|give|make|create|generate|draw|paint)(?:\s+me)?\s+(?P<context>that|that one|this|this one|it|one of that|one of it|one of them)\s*$",
    re.IGNORECASE,
)
_FOLLOWUP_STYLE_RE = re.compile(
    r"^(?:now\s+)?(?:make|show|display|pull up|give|create|generate|draw|paint)(?:\s+me)?\s+(?P<context>it|that|that one|this|this one|one of that|one of it|one of them)\s+(?P<modifier>.+)$",
    re.IGNORECASE,
)
_FOLLOWUP_TEXT_RE = re.compile(
    r"^(?:write|put)\s+(?P<modifier>.+?)\s+(?:on it|on that|on this|in the image|in that image)\s*$",
    re.IGNORECASE,
)
_FOLLOWUP_VISUAL_REF_RE = re.compile(
    r"^(?:show|display|pull up|give|make|create|generate)(?:\s+me)?\s+(?:a|an)?\s*(?:picture|image|photo|map|diagram|chart|visual|poster|banner|flyer|sign|graphic|card)\s+of\s+(?P<context>that city|that place|that map|that diagram|that picture|that image|that poster|that banner|that flyer|that sign|that graphic|that card|him|her|them|it|that|this|there)(?:\s+(?P<modifier>.+))?$",
    re.IGNORECASE,
)
_IMAGE_STYLE_WORDS = (
    "simple",
    "simpler",
    "cartoonish",
    "cartoony",
    "dramatic",
    "warmer",
    "clearer",
    "cleaner",
    "darker",
    "brighter",
)


def route_user_request(
    user_text: str,
    history: list[dict[str, str]] | None = None,
) -> dict[str, str | None]:
    fallback_prompt = _fallback_image_prompt(user_text, history)
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


def _fallback_image_prompt(
    user_text: str,
    history: list[dict[str, str]] | None,
) -> str | None:
    explicit_prompt = _resolve_prompt_with_history(extract_image_prompt(user_text), history)
    if explicit_prompt:
        return explicit_prompt
    return _extract_visual_followup_prompt(user_text, history)


def _resolve_prompt_with_history(
    prompt: str | None,
    history: list[dict[str, str]] | None,
) -> str | None:
    if not prompt:
        return prompt
    prompt = prompt.strip()
    if not history:
        return prompt
    subject = _recent_subject(history)
    if not subject:
        return prompt
    replaced = _replace_contextual_prompt(prompt, subject)
    if replaced:
        return replaced
    return prompt


def _prompt_needs_context(prompt: str) -> bool:
    cleaned = re.sub(r"[^a-zA-Z\s]", " ", prompt).strip().lower()
    if not cleaned:
        return False
    return cleaned in _PROMPTS_NEEDING_CONTEXT or bool(_CONTEXTUAL_PROMPT_RE.match(cleaned))


def _replace_contextual_prompt(prompt: str, subject: str) -> str | None:
    match = _CONTEXTUAL_PROMPT_RE.match(prompt.strip())
    if not match:
        return None
    rest = (match.group("rest") or "").strip()
    if rest:
        return _normalize_subject(f"{subject} {rest}")
    return _normalize_subject(subject)


def _recent_subject(history: list[dict[str, str]]) -> str | None:
    for message in reversed(history[-6:]):
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        subject = _extract_subject_from_message(content)
        if subject and not _prompt_needs_context(subject):
            return subject
    return None


def _recent_visual_subject(history: list[dict[str, str]] | None) -> str | None:
    if not history:
        return None
    for message in reversed(history[-6:]):
        if str(message.get("role", "")).strip() != "assistant":
            continue
        content = str(message.get("content", "")).strip()
        if not content:
            continue
        match = _DISPLAYED_IMAGE_RE.match(content)
        if match:
            return _normalize_subject(match.group("subject"))
    return None


def _extract_visual_followup_prompt(
    user_text: str,
    history: list[dict[str, str]] | None,
) -> str | None:
    if not history:
        return None
    candidate = _TRAILING_PUNCT_RE.sub("", clean_request_text(user_text)).strip()
    recent_visual = _recent_visual_subject(history)
    recent_subject = _recent_subject(history)

    match = _FOLLOWUP_VISUAL_REF_RE.match(candidate)
    if match:
        subject = recent_subject or recent_visual
        if not subject:
            return None
        return _compose_visual_followup_prompt(subject, match.group("modifier"))

    if not recent_visual:
        return None

    match = _FOLLOWUP_REPEAT_RE.match(candidate)
    if match:
        return recent_visual

    match = _FOLLOWUP_STYLE_RE.match(candidate)
    if match:
        return _compose_visual_followup_prompt(recent_visual, match.group("modifier"))

    match = _FOLLOWUP_TEXT_RE.match(candidate)
    if match:
        return _compose_visual_followup_prompt(recent_visual, f"with the words {match.group('modifier')}")

    return None


def _compose_visual_followup_prompt(subject: str, modifier: str | None) -> str | None:
    subject = _normalize_subject(subject)
    if not subject:
        return None
    modifier = _normalize_subject(modifier or "")
    if not modifier:
        return subject
    lower_modifier = modifier.lower()
    if lower_modifier.startswith(("with the words ", "that says ", "write ")):
        return f"{subject}, {modifier}"
    if any(lower_modifier.startswith(word) for word in _IMAGE_STYLE_WORDS):
        return f"{subject}, {modifier}"
    return f"{subject}, {modifier}"


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
