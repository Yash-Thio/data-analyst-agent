from pathlib import Path

_SKILLS_DIR = Path(__file__).resolve().parent


def load_skill(name: str) -> str:
    path = _SKILLS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8")
