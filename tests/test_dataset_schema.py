"""Dataset schemas agree with the records the pipeline really produces (fixture-based, offline)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.test_pipeline import _run

ACTOR = Path(__file__).parent.parent / ".actor"


def _schema(name: str) -> dict:
    return json.loads((ACTOR / name).read_text())


def _records(mode: str = "both") -> dict[str, list[dict]]:
    actor, _, _ = asyncio.run(_run({"cities": ["katowice"], "mode": mode}))
    return {t: actor.records(t) for t in ("areaYield", "scoredListing")}


def _flatten(record: dict, names: list[str]) -> set[str]:
    keys = set(record)
    for name in names:
        if isinstance(record.get(name), dict):
            keys |= {f"{name}.{k}" for k in record[name]}
    return keys


@pytest.mark.parametrize("schema_file,view,record_type", [
    ("dataset_schema.json", "overview", "scoredListing"),
    ("dataset_schema.json", "yields", "areaYield"),
    ("yields_dataset_schema.json", "yields", "areaYield"),
])
def test_view_fields_exist_in_records_and_have_labels(schema_file: str, view: str, record_type: str) -> None:
    spec = _schema(schema_file)["views"][view]
    fields, flatten = spec["transformation"]["fields"], spec["transformation"].get("flatten", [])
    records = _records()[record_type]
    assert records
    present = set().union(*(_flatten(r, flatten) for r in records))
    assert set(fields) <= present, set(fields) - present
    assert set(spec["display"]["properties"]) == set(fields)
    assert all(p["label"] and p["format"] for p in spec["display"]["properties"].values())


def test_default_schema_fields_are_permissive_and_cover_both_record_types() -> None:
    fields = _schema("dataset_schema.json")["fields"]
    assert "required" not in fields and fields.get("additionalProperties") is True
    assert "$schema" not in fields  # docs: only draft-07 value allowed, or omitted
    for name, prop in fields["properties"].items():
        types = prop["type"] if isinstance(prop["type"], list) else [prop["type"]]
        assert name == "recordType" or "null" in types, name
        assert prop["title"] and prop["description"]
    for rec in (r for rs in _records().values() for r in rs):
        assert set(rec) <= set(fields["properties"]), set(rec) - set(fields["properties"])


@pytest.mark.parametrize("mode", ["both", "yieldReport", "scoreListings"])
def test_every_record_validates_against_default_dataset_fields(mode: str) -> None:
    jsonschema = pytest.importorskip("jsonschema")
    fields = _schema("dataset_schema.json")["fields"]
    validator = jsonschema.Draft7Validator(fields)
    records = [r for rs in _records(mode).values() for r in rs]
    assert records
    for rec in records:
        assert not list(validator.iter_errors(rec)), (rec["recordType"], [e.message for e in validator.iter_errors(rec)])

