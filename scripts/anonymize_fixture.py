#!/usr/bin/env python3
"""Anonymize fixture JSON files before committing.

Replaces PII (agent names, contacts, agency names, addresses, images)
with test placeholders. Otodom fixtures only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def anonymize_otodom(data: dict) -> dict:
    items = (
        data.get("pageProps", {})
        .get("data", {})
        .get("searchAds", {})
        .get("items", [])
    )
    for i, item in enumerate(items):
        _anonymize_ad(item, str(i))
        # INVESTMENT tiles embed full unit ads, each with its own owner, agency and address
        for j, child in enumerate(item.get("relatedAds") or []):
            _anonymize_ad(child, f"{i}-{j}")
    return data


def _anonymize_ad(item: dict, n: str) -> None:
    owner = item.get("advertOwner")
    if isinstance(owner, dict):
        name = owner.get("name", "")
        if name:
            owner["name"] = f"Osoba Prywatna {n}" if "prywat" in name.lower() else f"Agent Testowy {n}"
        owner["imageUrl"] = ""
        for c in owner.get("contacts", []):
            c["name"] = f"Kontakt Testowy {n}"
            c["imageURLSmall"] = ""
            c.pop("phone", None)
            c.pop("email", None)

    m = item.get("organisationAssignedMember")
    if isinstance(m, dict):
        m["name"] = f"Agent Testowy {n}"
        if "firstName" in m:
            m["firstName"] = "Agent"
        if "lastName" in m:
            m["lastName"] = f"Testowy {n}"
        for key in ("userID", "profileID"):
            if key in m:
                m[key] = None
        for key in ("imageUrl", "photoURL"):
            if key in m:
                m[key] = ""
        m.pop("phone", None)
        m.pop("email", None)

    a = item.get("agency")
    if isinstance(a, dict):
        a["name"] = f"Agencja Testowa {n}"
        a["slug"] = f"agencja-testowa-{n}"
        a["imageUrl"] = ""
        a.pop("phone", None)
        a.pop("email", None)

    # free text: can contain names, phone numbers or a street
    if item.get("title"):
        item["title"] = f"Tytuł testowy {n}"
    if item.get("shortDescription"):
        item["shortDescription"] = f"Opis testowy {n}"

    imgs = item.get("images", [])
    if imgs and len(imgs) > 1:
        item["images"] = imgs[:1]

    loc = item.get("location") or {}
    addr = loc.get("address") or {}
    if "street" in addr:
        addr["street"] = {"name": None, "number": None}
    loc.pop("mapDetails", None)


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <fixture.json>")
        sys.exit(1)

    path = Path(sys.argv[1])
    data = json.loads(path.read_text())

    if "otodom" in path.name:
        data = anonymize_otodom(data)
    else:
        print(f"Unknown fixture type: {path.name}")
        sys.exit(1)

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"Anonymized: {path}")


if __name__ == "__main__":
    main()
