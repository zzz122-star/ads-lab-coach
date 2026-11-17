from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent / "content"


def _load(path: Path):
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_experiments() -> list:
    return [_load(p) for p in sorted((ROOT / "experiments").glob("*.yaml"))]


def load_diagnostics() -> list:
    return _load(ROOT / "diagnostics.yaml")


def load_cards() -> dict:
    return {p.stem: p.read_text(encoding="utf-8") for p in sorted((ROOT / "cards").glob("*.md"))}


def diagnose(query: str, entries: list, limit: int = 3) -> list:
    q = query.lower()
    scored = []
    for e in entries:
        score = sum(2 for k in e.get("keywords", []) if k.lower() in q)
        score += sum(1 for ch in set(e["symptom"]) if ch in q and not ch.isspace()) * 0.05
        if score > 0:
            scored.append((score, e))
    scored.sort(key=lambda t: -t[0])
    return [e for _, e in scored[:limit]]
