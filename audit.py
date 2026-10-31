"""Append-only audit log. Each record is hash-chained to the previous one,
so editing or deleting an old line is detected by verify()."""
import datetime
import hashlib
import json
import uuid

import config
from memory import redact


def _path():
    return config.runtime_path("audit.jsonl")


def _scrub(v):
    if isinstance(v, str):
        return redact(v)
    if isinstance(v, dict):
        return {k: _scrub(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_scrub(x) for x in v]
    return v


def _hash(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_all() -> list:
    p = _path()
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def log(actor, role, action, decision, result="", details=None):
    """decision: allowed | blocked | approval_required | approved | rejected | redacted ..."""
    if not config.CONTROLS_ENABLED:  # Assignment-1 baseline has no audit trail
        return None
    entries = read_all()
    body = {
        "audit_id": f"AUD-{len(entries) + 1:05d}",
        "ts": datetime.datetime.now().isoformat(timespec="seconds"),
        "actor": actor,
        "role": role,
        "action": action,
        "details": _scrub(details or {}),
        "decision": decision,
        "result": _scrub(result),
        "prev_hash": entries[-1]["hash"] if entries else "0" * 64,
    }
    body["hash"] = _hash(body)
    with _path().open("a", encoding="utf-8") as f:
        f.write(json.dumps(body, ensure_ascii=False) + "\n")
    return body


def verify():
    prev = "0" * 64
    for i, e in enumerate(read_all()):
        body = {k: v for k, v in e.items() if k != "hash"}
        if e["prev_hash"] != prev or e["hash"] != _hash(body):
            return False, i
        prev = e["hash"]
    return True, None
