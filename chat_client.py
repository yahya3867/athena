import json
from typing import Generator

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
            status_forcelist=[408, 429, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        _http_session.mount("http://", adapter)
        _http_session.mount("https://", adapter)
    return _http_session


def _build_input(user_text: str, history: list[dict] | None) -> str | list[dict]:
    if history:
        input_val: list[dict] = [
            {"type": "message", "role": message["role"], "content": message["content"]}
            for message in history
        ]
        input_val.append({"type": "message", "role": "user", "content": user_text})
        return input_val
    return user_text


def _tool_candidates() -> list[str]:
    configured = config.OPENAI_WEB_SEARCH_TOOL.strip() or "web_search_preview"
    candidates = [configured]
    for fallback in ("web_search_preview", "web_search"):
        if fallback not in candidates:
            candidates.append(fallback)
    return candidates


def _request_body(user_text: str, history: list[dict] | None, tool_type: str | None) -> dict:
    body = {
        "model": config.OPENAI_CHAT_MODEL,
        "stream": True,
        "input": _build_input(user_text, history),
        "instructions": config.OPENAI_CHAT_INSTRUCTIONS,
    }
    if config.OPENAI_ENABLE_WEB_SEARCH and tool_type:
        body["tools"] = [{"type": tool_type}]
    return body


def stream_response(
    user_text: str,
    history: list[dict] | None = None,
) -> Generator[str, None, None]:
    """Stream text deltas from OpenAI Responses API."""
    if not config.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is required for chat responses.")

    url = "https://api.openai.com/v1/responses"
    headers = {
        "Authorization": f"Bearer {config.OPENAI_API_KEY}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    last_error = ""
    for tool_type in _tool_candidates():
        body = _request_body(user_text, history, tool_type)
        try:
            resp = _get_session().post(
                url,
                json=body,
                headers=headers,
                stream=True,
                timeout=(30, 300),
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise RuntimeError(f"Chat request failed: {exc}") from exc

        if resp.status_code == 200:
            yield from _iter_sse_response(resp)
            return

        last_error = resp.text[:500]
        if resp.status_code == 400 and "web_search" in last_error and tool_type != _tool_candidates()[-1]:
            continue
        raise RuntimeError(f"Chat request failed ({resp.status_code}): {last_error}")

    raise RuntimeError(f"Unable to create chat response: {last_error}")


def _iter_sse_response(resp: requests.Response) -> Generator[str, None, None]:
    saw_text_delta = False
    for raw_line in resp.iter_lines(decode_unicode=True):
        if not raw_line:
            continue
        line = raw_line.strip()
        if not line.startswith("data:"):
            continue
        data_str = line[len("data:"):].strip()
        if not data_str or data_str == "[DONE]":
            continue
        try:
            data = json.loads(data_str)
        except json.JSONDecodeError:
            continue
        msg_type = data.get("type", "")
        if msg_type == "response.output_text.delta":
            delta = data.get("delta", "")
            if delta:
                saw_text_delta = True
                yield delta
        elif msg_type == "response.output_text.done":
            text = data.get("text", "")
            if text and not saw_text_delta:
                yield text
        elif msg_type == "response.content_part.added":
            part = data.get("part", {})
            text = part.get("text", "")
            if text:
                yield text
        elif msg_type == "response.completed":
            return
        elif msg_type == "error":
            err_msg = data.get("error", {}).get("message", str(data))
            raise RuntimeError(f"Chat stream error: {err_msg}")
