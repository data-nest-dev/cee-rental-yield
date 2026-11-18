#!/usr/bin/env python3
"""Anonymize fixture JSON files before committing.

Replaces PII (agent names, contacts, agency names, addresses, images)
with test placeholders. Works for both Otodom and Sreality fixtures.
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
        # advertOwner
        if "advertOwner" in item:
            owner = item["advertOwner"]
            if isinstance(owner, dict):
                name = owner.get("name", "")
                if name:
                    owner["name"] = f"Osoba Prywatna {i}" if "prywat" in name.lower() else f"Agent Testowy {i}"
                owner["imageUrl"] = ""
                for c in owner.get("contacts", []):
                    c["name"] = f"Kontakt Testowy {i}"
                    c["imageURLSmall"] = ""
                    c.pop("phone", None)
                    c.pop("email", None)

        # organisationAssignedMember
        if "organisationAssignedMember" in item:
            m = item["organisationAssignedMember"]
            if isinstance(m, dict):
                m["name"] = f"Agent Testowy {i}"
                m["imageUrl"] = ""
                m.pop("phone", None)
                m.pop("email", None)

        # agency
        if "agency" in item:
            a = item["agency"]
            if isinstance(a, dict):
                a["name"] = f"Agencja Testowa {i}"
                a["slug"] = f"agencja-testowa-{i}"
                a["imageUrl"] = ""
                a.pop("phone", None)
                a.pop("email", None)

        # Trim images to max 1
        imgs = item.get("images", [])
        if imgs and len(imgs) > 1:
            item["images"] = imgs[:1]

        # Remove street address
        addr = item.get("location", {}).get("address", {})
        if "street" in addr:
            addr["street"] = {"name": None, "number": None}

        # Remove map details
        loc = item.get("location", {})
        loc.pop("mapDetails", None)

    return data


def anonymize_sreality(data: dict) -> dict:
    ds = data.get("pageProps", {}).get("dehydratedState", {})
    for q in ds.get("queries", []):
        qk = q.get("queryKey", [])
        if isinstance(qk, list) and qk and qk[0] == "estatesSearch":
            results = q.get("state", {}).get("data", {}).get("results", [])
            for i, item in enumerate(results):
                # Trim images to 1
                imgs = item.get("images", [])
                if imgs and len(imgs) > 1:
                    item["images"] = imgs[:1]

                # Remove street info from locality
                loc = item.get("locality", {})
                loc.pop("street", None)
                loc.pop("streetId", None)
                loc.pop("streetSeoName", None)
                loc.pop("streetNumber", None)
                loc.pop("houseNumber", None)
                loc.pop("geoHash", None)
                loc.pop("latitude", None)
                loc.pop("longitude", None)

                # Remove premise (agency) details but keep premiseId
                item.pop("premiseLogo", None)

    return data


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <fixture.json>")
        sys.exit(1)

    path = Path(sys.argv[1])
    data = json.loads(path.read_text())

    if "otodom" in path.name:
        data = anonymize_otodom(data)
    elif "sreality" in path.name:
        data = anonymize_sreality(data)
    else:
        print(f"Unknown fixture type: {path.name}")
        sys.exit(1)

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    print(f"Anonymized: {path}")


if __name__ == "__main__":
    main()
