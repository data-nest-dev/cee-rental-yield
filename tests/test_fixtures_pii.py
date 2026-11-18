from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

FIXTURES = sorted((Path(__file__).parent / "fixtures").glob("*.json"))
PLACEHOLDER = re.compile(r"^(Agent Testowy|Agencja Testowa|Osoba Prywatna|Kontakt Testowy) [\w-]+$")
NAME_PART = re.compile(r"^(Agent|Testowy [\w-]+)$")
PERSON_KEYS = ("advertOwner", "agency", "organisationAssignedMember")
PERSON_ID_KEYS = ("userID", "profileID", "userId", "profileId")
URL_KEYS = ("imageUrl", "imageURLSmall", "photoURL", "photoUrl")


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
                for part in ("firstName", "lastName"):
                    if c.get(part) and not NAME_PART.match(c[part]):
                        problems.append(f"{path}.{key}.{part}: {c[part]!r}")
                for url_key in URL_KEYS:
                    if c.get(url_key):
                        problems.append(f"{path}.{key}.{url_key}: photo/logo URL")
                if key != "agency":
                    for id_key in PERSON_ID_KEYS:
                        if c.get(id_key) is not None:
                            problems.append(f"{path}.{key}.{id_key}: person id")
        if "slug" in node and "estate" in node:
            for text_key, prefix in (("title", "Tytuł testowy "), ("shortDescription", "Opis testowy ")):
                if node.get(text_key) and not str(node[text_key]).startswith(prefix):
                    problems.append(f"{path}.{text_key}: free text")
        street = (node.get("address") or {}).get("street") if isinstance(node.get("address"), dict) else None
        if isinstance(street, dict) and (street.get("name") or street.get("number")):
            problems.append(f"{path}.address.street")
        if len(node.get("images") or []) > 1:
            problems.append(f"{path}.images > 1")
    assert problems == []
