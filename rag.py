"""Tiny retrieval over ONE handbook file. No embeddings, no API tokens:
TF-IDF cosine + a coverage check so off-topic questions return nothing."""
import math
import re
from collections import Counter
from functools import lru_cache

import config

STOP = set("""a an the is are was were be been am i me my we you your to of in on at for from by with and or but if
so as it its this that these those can could should would will do does did how what when where which who whom
about any there their then than also please tell show give need want get have has had not no yes""".split())


def _stem(w: str) -> str:
    for suf in ("ments", "ment", "ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)]
            break
    if w.endswith("e") and len(w) > 4:
        w = w[:-1]
    return w


def _tok(text: str) -> list:
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP and len(w) > 1]


@lru_cache(maxsize=1)
def _index():
    raw = (config.DATA_DIR / "student_handbook.md").read_text(encoding="utf-8")
    chunks = []
    for block in re.split(r"(?m)^## ", raw)[1:]:
        title_line, _, body = block.partition("\n")
        cid, _, title = title_line.partition(" ")
        chunks.append({"id": cid, "title": title.strip(), "text": body.strip()})
    for c in chunks:
        # title words count double
        c["tf"] = Counter(_tok(c["text"]) + 2 * _tok(c["title"]))
    n = len(chunks)
    df = Counter(t for c in chunks for t in c["tf"])
    idf = {t: math.log((n + 1) / (d + 1)) + 1 for t, d in df.items()}
    unknown_idf = math.log(n + 1) + 1
    for c in chunks:
        vec = {t: f * idf[t] for t, f in c["tf"].items()}
        c["vec"] = vec
        c["norm"] = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return chunks, idf, unknown_idf


def search(query: str, k: int = None) -> list:
    k = k or config.TOP_K
    chunks, idf, unknown_idf = _index()
    q_tokens = _tok(query)
    if not q_tokens:
        return []
    q_tf = Counter(q_tokens)
    q_vec = {t: f * idf.get(t, unknown_idf) for t, f in q_tf.items()}
    q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
    total_weight = sum(idf.get(t, unknown_idf) for t in q_tf)
    results = []
    for c in chunks:
        dot = sum(v * c["vec"].get(t, 0.0) for t, v in q_vec.items())
        cosine = dot / (q_norm * c["norm"])
        covered = sum(idf.get(t, unknown_idf) for t in q_tf if t in c["vec"])
        coverage = covered / total_weight if total_weight else 0.0
        if cosine >= config.MIN_SCORE and coverage >= config.MIN_COVERAGE:
            results.append({"id": c["id"], "title": c["title"], "text": c["text"], "score": cosine})
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:k]
