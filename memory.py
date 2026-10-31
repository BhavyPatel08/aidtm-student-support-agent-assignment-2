"""Persistent long-term memory + sensitive-data guard.

Rules enforced in code:
  * only whitelisted, durable keys can be stored (programme, preferences ...)
  * anything that looks like an OTP / password / PIN / CVV / card / Aadhaar is never stored
  * temporary statements ("right now", "today") are never stored
  * only memory relevant to the current question is sent to the model
"""
import datetime
import json
import re

import config

# ---------------------------------------------------------------- sensitive data
SENSITIVE_RULES = [
    ("otp", re.compile(r"\b(?:otp|o[ .]t[ .]p|one[- ]time (?:password|code|pin)|verification code)\b[^0-9]{0,25}\d{4,8}", re.I)),
    ("password", re.compile(r"\b(?:password|passwd|passcode|pwd)\b\s*(?:is|=|:)\s*\S+", re.I)),
    ("pin", re.compile(r"\bpin\b\s*(?:is|=|:)?\s*\d{3,6}\b", re.I)),
    ("cvv", re.compile(r"\bcvv\b\s*(?:is|=|:)?\s*\d{3,4}\b", re.I)),
    ("card_number", re.compile(r"(?<![+\d])(?:\d{4}[ -]){3}\d{4}(?!\d)|(?<![+\d])\d{16}(?!\d)")),
    ("aadhaar", re.compile(r"(?<![+\d])\d{4}[ -]\d{4}[ -]\d{4}(?!\d)|(?<![+\d])\d{12}(?!\d)")),
]


def contains_sensitive(text: str) -> list:
    return [name for name, rx in SENSITIVE_RULES if rx.search(text or "")]


def redact(text: str) -> str:
    out = text or ""
    for name, rx in SENSITIVE_RULES:
        out = rx.sub(f"[REDACTED:{name}]", out)
    return out


# ---------------------------------------------------------------- memory store
ALLOWED_KEYS = {
    "programme": {"programme", "program", "course", "pgdm", "batch", "studying", "enrolled"},
    "preferred_contact": {"contact", "contacted", "reach", "reached", "call", "whatsapp", "email", "phone", "message", "notify"},
    "preferred_language": {"language", "reply", "respond", "speak", "hindi", "gujarati", "english", "communicate"},
    "preferred_name": {"name", "address", "refer"},
    "study_interest": {"interest", "interested", "specialisation", "specialization", "elective", "career", "focus"},
}
TEMPORARY_WORDS = re.compile(
    r"\b(today|tonight|tomorrow|right now|this (?:morning|evening|week)|currently at|at the moment)\b", re.I
)


def _path():
    return config.runtime_path("memory.json")


def _load() -> dict:
    p = _path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save(user_id: str, key: str, value: str):
    """Returns (ok, reason). All checks are plain code - not LLM instructions."""
    key = (key or "").strip().lower()
    value = (value or "").strip()
    if key not in ALLOWED_KEYS:
        return False, f"'{key}' is not a long-term memory field"
    if not (2 <= len(value) <= 80) or "\n" in value:
        return False, "value must be a short single line"
    if contains_sensitive(value) or any(rx.search(key + " " + value) for _, rx in SENSITIVE_RULES):
        return False, "sensitive information is never stored"
    if TEMPORARY_WORDS.search(value):
        return False, "temporary information is not stored"
    data = _load()
    data.setdefault(user_id, {})[key] = {"value": value, "updated": datetime.date.today().isoformat()}
    _path().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return True, "saved"


def load_all(user_id: str) -> dict:
    return {k: v["value"] for k, v in _load().get(user_id, {}).items()}


def select_relevant(user_id: str, question: str) -> dict:
    """Context selection for memory: return only items related to this question."""
    words = set(re.findall(r"[a-z]+", (question or "").lower()))
    chosen = {}
    for key, value in load_all(user_id).items():
        value_words = set(re.findall(r"[a-z]+", value.lower()))
        if words & ALLOWED_KEYS.get(key, set()) or words & value_words:
            chosen[key] = value
    return chosen


_EXTRACTORS = [
    ("programme", re.compile(r"\bmy (?:programme|program) is ([A-Za-z&/ \-]{3,60}?)(?:[.,!?]|$)", re.I)),
    ("preferred_contact", re.compile(r"\bprefer(?: to be)? (?:contacted|reached) (?:on|via|by|through) (?:the )?([A-Za-z]+)", re.I)),
    ("preferred_language", re.compile(r"\bprefer (?:replies|answers|responses|communication) in ([A-Za-z]+)", re.I)),
    ("preferred_name", re.compile(r"\bcall me ([A-Z][a-z]+)")),
]


def extract_candidates(text: str) -> list:
    out = []
    for key, rx in _EXTRACTORS:
        m = rx.search(text or "")
        if m:
            out.append((key, m.group(1).strip()))
    return out


# ---------------------------------------------------------------- voice input
_DIGIT_WORDS = {"zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
                "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9"}


def normalize_spoken(text: str) -> str:
    """Speech-to-text may give 'four eight two nine one three' or '4 8 2 9 1 3'.
    Turn digit runs (4+ digits) into plain digits so the sensitive-data check can see them."""
    words, out, run = (text or "").split(), [], []

    def flush():
        if len(run) >= 4:
            out.append("".join(_DIGIT_WORDS[w.lower().strip(",.")] for w in run))
        else:
            out.extend(run)
        run.clear()

    for w in words:
        if w.lower().strip(",.") in _DIGIT_WORDS:
            run.append(w)
        else:
            flush()
            out.append(w)
    flush()
    joined = " ".join(out)
    return re.sub(r"(?<![\d+])(?:\d[ ,.-]){3,}\d(?!\d)", lambda mt: re.sub(r"\D", "", mt.group(0)), joined)
