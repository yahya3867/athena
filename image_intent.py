import re


_ATHENA_PREFIX = re.compile(r"^\s*(?:hey\s+)?athena[\s,:\-]*", re.IGNORECASE)
_TRAILING_PUNCT = re.compile(r"[\s\.\!\?]+$")
_POLITE_PREFIX = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you|will you)\s+)*(?:go ahead and\s+)?",
    re.IGNORECASE,
)
_LEADIN_PREFIX = re.compile(
    r"^\s*(?:i was wondering if you can\s+|i was wondering if you could\s+|i was wondering whether you can\s+|i was wondering whether you could\s+)",
    re.IGNORECASE,
)
_IMAGE_PATTERNS = [
    re.compile(
        r"^show me (?:a|an)?\s*(?:picture|image|photo|drawing|illustration) of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:generate|create|make) (?:me\s+)?(?:a|an)?\s*(?:picture|image|photo|drawing|illustration) of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:generate|create|make) (?:me\s+)?(?:a|an)?\s*(?:picture|image|photo|drawing|illustration) (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^draw (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^paint (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
]


def extract_image_prompt(text: str) -> str | None:
    candidate = (text or "").strip()
    if not candidate:
        return None
    candidate = _ATHENA_PREFIX.sub("", candidate).strip()
    candidate = _LEADIN_PREFIX.sub("", candidate).strip()
    candidate = _POLITE_PREFIX.sub("", candidate).strip()
    for pattern in _IMAGE_PATTERNS:
        match = pattern.match(candidate)
        if not match:
            continue
        prompt = match.group("prompt").strip()
        prompt = _normalize_prompt(prompt)
        if prompt:
            return prompt
    return _extract_image_prompt_from_sentences(candidate)


def _extract_image_prompt_from_sentences(candidate: str) -> str | None:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", candidate) if part.strip()]
    if not parts:
        return None
    for idx, part in enumerate(parts):
        for pattern in _IMAGE_PATTERNS:
            match = pattern.match(part)
            if not match:
                continue
            prompt = match.group("prompt").strip()
            tail = " ".join(parts[idx + 1 :]).strip()
            if tail:
                prompt = f"{prompt}. {tail}"
            prompt = _normalize_prompt(prompt)
            if prompt:
                return prompt
    return None


def _normalize_prompt(prompt: str) -> str | None:
    prompt = prompt.strip()
    prompt = _TRAILING_PUNCT.sub("", prompt).strip()
    if prompt:
        prompt = _TRAILING_PUNCT.sub("", prompt).strip()
    return prompt or None
