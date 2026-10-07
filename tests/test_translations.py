import json
from pathlib import Path

import pytest

TRANSLATIONS = Path(__file__).parent.parent / "custom_components/kvartac/translations"


def _keys(data: dict, prefix: str = "") -> set[str]:
    keys = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        keys |= _keys(value, path) if isinstance(value, dict) else {path}
    return keys


@pytest.mark.parametrize("path", sorted(TRANSLATIONS.glob("*.json")), ids=str)
def test_same_keys(path: Path) -> None:
    en = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert _keys(data) == _keys(en)
