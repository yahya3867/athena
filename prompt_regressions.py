from __future__ import annotations

from dataclasses import dataclass, field

import config
from intent_router import route_user_request
from local_status import maybe_answer_local_status


@dataclass(frozen=True)
class PromptCase:
    name: str
    transcript: str
    expected_route: str
    history: list[dict[str, str]] = field(default_factory=list)
    expected_prompt: str | None = None
    expected_prompt_contains: tuple[str, ...] = ()
    expected_prompt_any_of: tuple[str, ...] = ()
    expected_local_contains: tuple[str, ...] = ()


PROMPT_CASES: list[PromptCase] = [
    PromptCase(
        name="local-battery-percentage",
        transcript="What's your current battery percentage?",
        expected_route="local",
        expected_local_contains=("battery",),
    ),
    PromptCase(
        name="local-plug-in",
        transcript="Do I plug you in?",
        expected_route="local",
        expected_local_contains=("battery",),
    ),
    PromptCase(
        name="local-wifi",
        transcript="What Wi-Fi are you on?",
        expected_route="local",
        expected_local_contains=("wi-fi",),
    ),
    PromptCase(
        name="local-online",
        transcript="Are you online right now?",
        expected_route="local",
        expected_local_contains=("online",),
    ),
    PromptCase(
        name="local-device-model",
        transcript="What device are you running on?",
        expected_route="local",
        expected_local_contains=("running on",),
    ),
    PromptCase(
        name="local-time",
        transcript="What's the current time right now?",
        expected_route="local",
        expected_local_contains=("it's",),
    ),
    PromptCase(
        name="negative-world-time",
        transcript="What's the time in Washington, D.C.?",
        expected_route="chat",
    ),
    PromptCase(
        name="negative-battery-knowledge",
        transcript="What battery does a Tesla use?",
        expected_route="chat",
    ),
    PromptCase(
        name="negative-wifi-knowledge",
        transcript="How does Wi-Fi work?",
        expected_route="chat",
    ),
    PromptCase(
        name="image-sourdough",
        transcript="Give me a picture of sourdough bread.",
        expected_route="image",
        expected_prompt="sourdough bread",
    ),
    PromptCase(
        name="image-map-casablanca",
        transcript="Show me a map of Casablanca.",
        expected_route="image",
        expected_prompt="Casablanca",
    ),
    PromptCase(
        name="image-poster-text",
        transcript="Generate a poster that says Happy Birthday.",
        expected_route="image",
        expected_prompt_contains=("poster", "happy birthday"),
    ),
    PromptCase(
        name="image-banner-text",
        transcript="Create a banner with the words Welcome Home.",
        expected_route="image",
        expected_prompt_contains=("banner", "welcome home"),
    ),
    PromptCase(
        name="image-pull-up-photo",
        transcript="Pull up a photo of Paris.",
        expected_route="image",
        expected_prompt="Paris",
    ),
    PromptCase(
        name="image-visualize-router",
        transcript="Help me visualize how to restart a Wi-Fi router.",
        expected_route="image",
        expected_prompt_contains=("restart a wi-fi router",),
    ),
    PromptCase(
        name="image-simple-diagram",
        transcript="Make me a simple diagram of the water cycle.",
        expected_route="image",
        expected_prompt_contains=("water cycle",),
    ),
    PromptCase(
        name="image-display-picture",
        transcript="Display a picture of ancient Athens at sunset.",
        expected_route="image",
        expected_prompt_contains=("ancient athens", "sunset"),
    ),
    PromptCase(
        name="negative-casablanca-chat",
        transcript="Tell me about Casablanca.",
        expected_route="chat",
    ),
    PromptCase(
        name="negative-map-projection-chat",
        transcript="Explain what a map projection is.",
        expected_route="chat",
    ),
    PromptCase(
        name="followup-person-pronoun",
        history=[
            {"role": "user", "content": "Who's the Dalai Lama?"},
            {"role": "assistant", "content": "The Dalai Lama is Tenzin Gyatso."},
        ],
        transcript="Give me a picture of him.",
        expected_route="image",
        expected_prompt_any_of=("tenzin gyatso", "dalai lama"),
    ),
    PromptCase(
        name="followup-person-name-beats-title",
        history=[
            {"role": "user", "content": "Who is the current president of Syria?"},
            {
                "role": "assistant",
                "content": "The current president of Syria is Ahmad al-Sharaa. Bashar al-Assad was the previous president.",
            },
        ],
        transcript="Show me a picture of him.",
        expected_route="image",
        expected_prompt_contains=("portrait photo", "ahmad al-sharaa"),
    ),
    PromptCase(
        name="followup-place-reference",
        history=[
            {"role": "user", "content": "Tell me about Delhi."},
            {"role": "assistant", "content": "Delhi is India's capital."},
        ],
        transcript="Give me a picture of that city.",
        expected_route="image",
        expected_prompt_contains=("delhi",),
    ),
    PromptCase(
        name="followup-image-style",
        history=[
            {"role": "user", "content": "Show me a map of Casablanca."},
            {"role": "assistant", "content": "Displayed an image of Casablanca."},
        ],
        transcript="Now make it dramatic.",
        expected_route="image",
        expected_prompt_contains=("casablanca", "dramatic"),
    ),
    PromptCase(
        name="followup-image-text",
        history=[
            {"role": "user", "content": "Show me a map of Casablanca."},
            {"role": "assistant", "content": "Displayed an image of Casablanca."},
        ],
        transcript="Write Happy Birthday on it.",
        expected_route="image",
        expected_prompt_contains=("casablanca", "happy birthday"),
    ),
    PromptCase(
        name="followup-image-repeat",
        history=[
            {"role": "user", "content": "Show me a picture of Paris."},
            {"role": "assistant", "content": "Displayed an image of Paris."},
        ],
        transcript="Show me that.",
        expected_route="image",
        expected_prompt_contains=("paris",),
    ),
    PromptCase(
        name="followup-chat-should-stay-chat",
        history=[
            {"role": "user", "content": "Explain recursion."},
            {"role": "assistant", "content": "Recursion is when a function calls itself."},
        ],
        transcript="Make it simpler.",
        expected_route="chat",
    ),
]


def run_prompt_regressions(verbose: bool = True) -> tuple[int, int]:
    failures = 0
    total = len(PROMPT_CASES)
    saved_key = config.OPENAI_API_KEY
    config.OPENAI_API_KEY = ""
    try:
        for case in PROMPT_CASES:
            ok, detail = _run_case(case)
            if verbose:
                status = "PASS" if ok else "FAIL"
                print(f"[{status}] {case.name}: {detail}")
            if not ok:
                failures += 1
    finally:
        config.OPENAI_API_KEY = saved_key
    return failures, total


def _run_case(case: PromptCase) -> tuple[bool, str]:
    local_response = maybe_answer_local_status(case.transcript)

    if case.expected_route == "local":
        if not local_response:
            return False, "expected local response but matcher returned None"
        lowered = local_response.lower()
        missing = [part for part in case.expected_local_contains if part.lower() not in lowered]
        if missing:
            return False, f"local response missing {missing}: {local_response!r}"
        return True, local_response

    if local_response is not None:
        return False, f"unexpected local match: {local_response!r}"

    route = route_user_request(case.transcript, history=case.history)
    if route.get("mode") != case.expected_route:
        return False, f"expected {case.expected_route}, got {route!r}"

    if case.expected_route != "image":
        return True, f"route={route.get('mode')}"

    prompt = (route.get("image_prompt") or "").strip()
    if not prompt:
        return False, f"expected image prompt, got {route!r}"
    if case.expected_prompt is not None and prompt != case.expected_prompt:
        return False, f"expected prompt {case.expected_prompt!r}, got {prompt!r}"

    lowered = prompt.lower()
    missing = [part for part in case.expected_prompt_contains if part.lower() not in lowered]
    if missing:
        return False, f"image prompt missing {missing}: {prompt!r}"

    if case.expected_prompt_any_of and not any(part.lower() in lowered for part in case.expected_prompt_any_of):
        return False, f"image prompt did not contain any of {case.expected_prompt_any_of}: {prompt!r}"

    return True, prompt
