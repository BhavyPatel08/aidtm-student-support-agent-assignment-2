"""Voice event handling kept separate from the UI so it can be unit-tested."""
import re


def speakable(text: str, limit: int = 420) -> str:
    """Plain text for text-to-speech: no markdown symbols, short."""
    t = re.sub(r"[*_`#>|]", " ", text or "")
    t = re.sub(r"\s+", " ", t).strip()
    if len(t) > limit:
        cut = t[:limit]
        t = cut[: cut.rfind(". ") + 1] if ". " in cut else cut
    return t


def friendly_error(exc) -> str:
    """Plain-language message for the most common free-tier problems."""
    text = str(exc).lower()
    if "429" in text or "rate" in text or "quota" in text or "limit" in text:
        return "The free AI model is busy (rate limit). Please wait about a minute and try again."
    if "401" in text or "api key" in text or "unauthorized" in text or "invalid_api_key" in text:
        return "The API key was rejected. Check GROQ_API_KEY in your .env file."
    if "timeout" in text or "connection" in text:
        return "Could not reach the AI service. Check your internet connection and try again."
    return "Sorry, something went wrong. Please try again."


def handle_event(state, ev, agent) -> bool:
    """Process one event from the browser voice widget. Returns True if the UI should rerun.
    `state` is st.session_state (or any dict). Each event id is handled exactly once."""
    if not isinstance(ev, dict) or ev.get("id") is None or ev["id"] == state.get("voice_last_event"):
        return False
    state["voice_last_event"] = ev["id"]
    kind = ev.get("type")
    if kind == "start":
        state["voice_active"] = True
        return True
    if kind == "stop":
        state["voice_active"] = False
        return True
    if kind == "question" and str(ev.get("text", "")).strip():
        try:
            t = agent.chat(ev["text"], channel="voice")
            reply = speakable(t["answer"])
            state["chat"] = list(state.get("chat", [])) + [
                {"role": "user", "content": t["question"], "channel": "voice"},
                {"role": "assistant", "content": t["answer"], "trace": t},
            ]
        except Exception as exc:  # never leave the caller hanging in silence
            reply = friendly_error(exc)
            state["voice_error"] = friendly_error(exc)
        state["voice_answer"] = reply
        state["voice_answer_id"] = state.get("voice_answer_id", 0) + 1
        return True
    return False
