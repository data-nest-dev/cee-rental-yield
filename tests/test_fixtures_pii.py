from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.json"))
PLACEHOLDER = re.compile(r"^(Agent Testowy|Agencja Testowa|Osoba Prywatna|Kontakt Testowy) [\w-]+$")
PERSON_KEYS = ("advertOwner", "agency", "organisationAssignedMember")


def _walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: p.name)
def test_no_real_names_streets_or_contacts(fixture: Path) -> None:
    problems = []
    for path, node in _walk(json.loads(fixture.read_text())):
        for key in PERSON_KEYS:
            entity = node.get(key)
            if not isinstance(entity, dict):
                continue
            names = [entity.get("name")] + [c.get("name") for c in entity.get("contacts") or []]
            for name in names:
                if name and not PLACEHOLDER.match(name):
                    problems.append(f"{path}.{key}: {name!r}")
            for c in [entity] + list(entity.get("contacts") or []):
                if c.get("phone") or c.get("email"):
                    problems.append(f"{path}.{key}: phone/email")
        street = (node.get("address") or {}).get("street") if isinstance(node.get("address"), dict) else None
        if isinstance(street, dict) and (street.get("name") or street.get("number")):
            problems.append(f"{path}.address.street")
        if len(node.get("images") or []) > 1:
            problems.append(f"{path}.images > 1")
    assert problems == []
