"""Student record store (JSON). A live copy is made in the runtime folder so the
original sample data is never modified."""
import json
import shutil

import config


def _live():
    path = config.runtime_path("students_live.json")
    if not path.exists():
        shutil.copy(config.DATA_DIR / "students.json", path)
    return path


def _load() -> dict:
    return json.loads(_live().read_text(encoding="utf-8"))


def get(student_id: str):
    return _load().get((student_id or "").strip().upper())


def resolve(identifier: str):
    """Map a student id OR a name mentioned by the model to a student id."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    data = _load()
    if ident.upper() in data:
        return ident.upper()
    low = ident.lower()
    for sid, rec in data.items():
        name = rec["name"].lower()
        if name == low or name in low:
            return sid
    return None


def update(student_id: str, patch: dict) -> None:
    data = _load()
    data[student_id].update(patch)
    _live().write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
