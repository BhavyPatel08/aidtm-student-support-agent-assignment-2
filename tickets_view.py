import json

import config


def load() -> list:
    p = config.runtime_path("tickets.json")
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
