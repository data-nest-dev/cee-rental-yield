"""The .actor definition files agree with each other and with the code."""
from __future__ import annotations

import json
from pathlib import Path

from src.charging import YIELDS_DATASET
from src.inputs import DEFAULT_PROXY, PREFILL_INPUT

ACTOR = Path(__file__).parent.parent / ".actor"


def _load(name: str) -> dict:
    return json.loads((ACTOR / name).read_text())


def test_actor_json_declares_default_and_yields_datasets_with_existing_schema_files() -> None:
    actor = _load("actor.json")
    datasets = actor["storages"]["datasets"]
    assert set(datasets) == {"default", YIELDS_DATASET} and "dataset" not in actor["storages"]
    for rel in datasets.values():
        assert (ACTOR / rel).is_file()
    assert (ACTOR / actor["output"]).is_file()


def test_yields_schema_has_only_the_yield_view_and_default_leads_with_scored_listings() -> None:
    assert list(_load("yields_dataset_schema.json")["views"]) == ["yields"]
    assert list(_load("dataset_schema.json")["views"]) == ["overview", "yields"]


def test_output_schema_links_both_datasets() -> None:
    props = _load("output_schema.json")["properties"]
    templates = {p["template"] for p in props.values()}
    assert templates == {"{{links.apiDefaultDatasetUrl}}/items", f"{{{{storages.datasets.{YIELDS_DATASET}.apiUrl}}}}/items"}
    assert all(p["title"] for p in props.values())


def test_default_and_prefill_proxy_name_no_group() -> None:
    assert DEFAULT_PROXY == {"useApifyProxy": True} and PREFILL_INPUT["proxyConfiguration"] == DEFAULT_PROXY
    for key in ("default", "prefill"):
        assert _load("input_schema.json")["properties"]["proxyConfiguration"][key] == {"useApifyProxy": True}


def test_actor_title_and_description_do_not_advertise_katowice() -> None:
    actor = _load("actor.json")
    assert actor["title"] == "Poland Rental Yield & Property Deal Score"
    assert "Katowice" not in actor["description"] and "scraper" not in actor["description"].lower()
