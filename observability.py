"""Optional LangSmith tracing  (https://smith.langchain.com).

OFF by default. Turn it on in .env:
    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=...            (your key - never commit it)
    LANGSMITH_PROJECT=aidtm-college-helpdesk

What you see in LangSmith for every student question (one trace = one question):
    support_agent_turn            root: question, final answer, data sources, total tokens, latency
      |- memory_lookup            retriever: which saved memory items were selected
      |- groq_chat_completion     llm: exact messages sent, tool calls returned, input/output tokens
      |- tool:get_fee_status      tool: arguments, allow/block decision, data returned, data source
      |- tool:search_policy       retriever: handbook sections returned with their scores
      '- groq_chat_completion     llm: final answer + tokens

Privacy: OTP/password/PIN/card patterns are ALWAYS redacted and emails/phone numbers are masked
before anything leaves this machine (set LANGSMITH_MASK_PII=0 to keep emails/phones readable).
If LangSmith is off, not installed, or unreachable the app keeps working normally.
"""
import atexit
import os
import re
from contextlib import contextmanager
from functools import lru_cache

import config  # noqa: F401  (loads .env before we read the variables below)
import memory

DEFAULT_PROJECT = "aidtm-college-helpdesk"

# Accept the older LANGCHAIN_* names too (used by the earlier College desk project).
for _new, _old in (("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"), ("LANGSMITH_PROJECT", "LANGCHAIN_PROJECT"),
                   ("LANGSMITH_ENDPOINT", "LANGCHAIN_ENDPOINT")):
    if not os.getenv(_new) and os.getenv(_old):
        os.environ[_new] = os.environ[_old]
os.environ.setdefault("LANGSMITH_PROJECT", DEFAULT_PROJECT)

_FLAG = (os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2") or "").strip().lower() in ("1", "true", "yes", "on")
_KEY = os.getenv("LANGSMITH_API_KEY", "").strip()
ENABLED = _FLAG and bool(_KEY) and not _KEY.lower().startswith("your_")  # ignore the placeholder from .env.example
if ENABLED:
    os.environ["LANGSMITH_TRACING"] = "true"
PROJECT = os.environ["LANGSMITH_PROJECT"]
MASK_PII = os.getenv("LANGSMITH_MASK_PII", "1") != "0"


def status() -> dict:
    if ENABLED:
        return {"enabled": True, "project": PROJECT, "reason": "tracing to LangSmith"}
    if _FLAG:
        return {"enabled": False, "project": PROJECT, "reason": "LANGSMITH_API_KEY is missing or still the placeholder"}
    return {"enabled": False, "project": PROJECT, "reason": "LANGSMITH_TRACING is not true"}


# ------------------------------------------------------------------ privacy filter
_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")
_PHONE = re.compile(r"(?<![\w.])\+?\d[\d ()-]{8,}\d(?![\w])")


def _mask_phone(m):
    digits = re.sub(r"\D", "", m.group(0))
    if len(digits) < 10 or re.fullmatch(r"\d{4}-\d{2}-\d{2}", m.group(0)):
        return m.group(0)  # dates and short numbers are left alone
    return "*" * (len(digits) - 4) + digits[-4:]


def scrub_text(text: str) -> str:
    text = memory.redact(text)  # OTP / password / PIN / CVV / card / Aadhaar - always
    if MASK_PII:
        text = _EMAIL.sub(r"\1***\2", text)
        text = _PHONE.sub(_mask_phone, text)
    return text


def scrub(obj):
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [scrub(v) for v in obj]
    return obj


# ------------------------------------------------------------------ client + spans
@lru_cache(maxsize=1)
def _client():
    from langsmith import Client
    return Client(hide_inputs=scrub, hide_outputs=scrub)


class _Span:
    """Thin handle so callers never need to care whether tracing is on."""

    def __init__(self, run=None):
        self.run = run

    @property
    def run_id(self):
        return str(self.run.id) if self.run is not None else None

    def end(self, outputs=None, metadata=None):
        if self.run is not None:
            try:
                self.run.end(outputs=outputs if isinstance(outputs, dict) else {"output": outputs}, metadata=metadata)
            except Exception:
                pass


@contextmanager
def span(name: str, run_type: str = "chain", inputs=None, tags=None, metadata=None):
    """Open a LangSmith run. Child spans nest automatically. No-op when tracing is off."""
    if not ENABLED:
        yield _Span()
        return
    try:
        import langsmith as ls
        ctx = ls.tracing_context(enabled=True)  # explicit: do not depend on the SDK's cached env flag
        cm = ls.trace(name=name, run_type=run_type, inputs=inputs or {}, tags=tags or [],
                      metadata=metadata or {}, client=_client(), project_name=PROJECT)
    except Exception:  # tracing problems must never break the app
        yield _Span()
        return
    with ctx, cm as run:
        yield _Span(run)


def flush() -> None:
    """Send any queued traces now (needed for short scripts such as eval.py)."""
    if ENABLED:
        try:
            _client().flush()
        except Exception:
            pass


atexit.register(flush)
