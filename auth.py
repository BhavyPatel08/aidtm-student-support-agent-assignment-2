"""Sign-in. The Session object is the ONLY source of 'who is the user'.
The LLM never supplies or changes identity."""
import hashlib
import hmac
import json
from dataclasses import dataclass

import config


@dataclass(frozen=True)
class Session:
    user_id: str
    name: str
    role: str  # "student" | "staff"


def hash_pin(pin: str) -> str:
    return hashlib.sha256(f"aidtm-demo:{pin}".encode()).hexdigest()


def authenticate(user_id: str, pin: str):
    users = json.loads((config.DATA_DIR / "users.json").read_text(encoding="utf-8"))
    user = users.get((user_id or "").strip().upper())
    if user and hmac.compare_digest(user["pin_hash"], hash_pin(pin or "")):
        return Session(user_id=(user_id or "").strip().upper(), name=user["name"], role=user["role"])
    return None
