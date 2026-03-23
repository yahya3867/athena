import re


_ATHENA_PREFIX = re.compile(r"^\s*(?:hey\s+)?athena[\s,:\-]*", re.IGNORECASE)
_TRAILING_PUNCT = re.compile(r"[\s\.\!\?]+$")
_TRAILING_POLITE = re.compile(r"(?:,\s*)?please\s*$", re.IGNORECASE)
_POLITE_PREFIX = re.compile(
    r"^\s*(?:(?:please|can you|could you|would you|will you)\s+)*(?:go ahead and\s+)?",
    re.IGNORECASE,
)
_LEADIN_PREFIX = re.compile(
    r"^\s*(?:i was wondering if you can\s+|i was wondering if you could\s+|i was wondering whether you can\s+|i was wondering whether you could\s+|i want you to\s+|i need you to\s+|i would like you to\s+)",
    re.IGNORECASE,
)
_VISUAL_NOUNS = "picture|image|photo|drawing|illustration|map|diagram|chart|visual|poster|banner|flyer|sign|graphic|card"
_IMAGE_PATTERNS = [
    re.compile(
        r"^show me (?:a|an)?\s*(?:picture|image|photo|drawing|illustration) of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^can i have (?:a|an)?\s*(?:picture|image|photo|drawing|illustration|map|diagram|chart|visual) of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^give me (?:a|an)?\s*(?:picture|image|photo|drawing|illustration|map|diagram|chart|visual) of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:display|pull up) (?:me\s+)?(?:a|an)?\s*(?:{_VISUAL_NOUNS}) of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:show|give|make|create|generate|display|pull up) (?:me\s+)?(?:a|an)?\s*(?P<kind>poster|banner|flyer|sign|graphic|card)(?:\s+that\s+says|\s+that\s+reads|\s+with(?:\s+the)?\s+words|\s+with\s+text)\s+(?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:show|give|make|create|generate|display|pull up) (?:me\s+)?(?:a|an)?\s*(?P<kind>picture|image|photo|graphic|card)(?:\s+that\s+says|\s+that\s+reads|\s+with(?:\s+the)?\s+words|\s+with\s+text)\s+(?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:generate|create|make) (?:me\s+)?(?:a|an)?\s*(?:picture|image|photo|drawing|illustration|poster|banner|flyer|sign|graphic|card) of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:generate|create|make) (?:me\s+)?(?:a|an)?\s*(?:picture|image|photo|drawing|illustration|poster|banner|flyer|sign|graphic|card) (?P<prompt>.+)$",
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
    re.compile(
        r"^show me (?:a|an)?\s*(?:map|diagram|chart|visual|illustration|poster|banner|flyer|sign|graphic|card) of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:generate|create|make) (?:me\s+)?(?:a|an)?\s*(?:map|diagram|chart|visual|illustration|poster|banner|flyer|sign|graphic|card) of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:generate|create|make) (?:me\s+)?(?:a|an)?\s*(?:map|diagram|chart|visual|illustration|poster|banner|flyer|sign|graphic|card) (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^show me where (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^help me visualize (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:make|create|generate) (?:me\s+)?(?:a|an)?\s*simple diagram of (?P<prompt>.+)$",
        re.IGNORECASE,
    ),
]


def clean_request_text(text: str) -> str:
    candidate = (text or "").strip()
    candidate = _ATHENA_PREFIX.sub("", candidate).strip()
    candidate = _LEADIN_PREFIX.sub("", candidate).strip()
    candidate = _POLITE_PREFIX.sub("", candidate).strip()
    return candidate


def extract_image_prompt(text: str) -> str | None:
    candidate = clean_request_text(text)
    if not candidate:
        return None
    for pattern in _IMAGE_PATTERNS:
        match = pattern.match(candidate)
        if not match:
            continue
        prompt = match.group("prompt").strip()
        kind = match.groupdict().get("kind")
        if kind:
            prompt = f"{kind.strip()} with the words {prompt}"
        prompt = _normalize_prompt(prompt)
        if prompt:
            return prompt
    return _extract_image_prompt_from_sentences(candidate)


def _extract_image_prompt_from_sentences(candidate: str) -> str | None:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+|,\s*", candidate) if part.strip()]
    if not parts:
        return None
    for idx, part in enumerate(parts):
        cleaned = _ATHENA_PREFIX.sub("", part).strip()
        cleaned = _LEADIN_PREFIX.sub("", cleaned).strip()
        cleaned = _POLITE_PREFIX.sub("", cleaned).strip()
        for pattern in _IMAGE_PATTERNS:
            match = pattern.match(cleaned)
            if not match:
                continue
            prompt = match.group("prompt").strip()
            kind = match.groupdict().get("kind")
            if kind:
                prompt = f"{kind.strip()} with the words {prompt}"
            tail = " ".join(parts[idx + 1 :]).strip()
            if tail:
                prompt = f"{prompt}. {tail}"
            prompt = _normalize_prompt(prompt)
            if prompt:
                return prompt
    return None


def _normalize_prompt(prompt: str) -> str | None:
    prompt = prompt.strip()
    prompt = _TRAILING_POLITE.sub("", prompt).strip()
    prompt = _TRAILING_PUNCT.sub("", prompt).strip()
    if prompt.lower().startswith("that says"):
        prompt = f"poster {prompt}"
    if prompt:
        prompt = _TRAILING_POLITE.sub("", prompt).strip()
        prompt = _TRAILING_PUNCT.sub("", prompt).strip()
    return prompt or None
