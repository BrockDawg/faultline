"""The real packs under packs/ load through the loader and keep their declared shape."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from faultline.pack import load_pack, load_packs

PACKS_ROOT = Path(__file__).resolve().parent.parent / "packs"

EXPECTED_PACKS = {
    "oval",
    "road-gt",
    "open-wheel",
    "forklift-operating-travel",
    "forklift-loads-stacking",
    "forklift-pedestrians-site",
    "forklift-truck-checks-fuelling",
}

FORKLIFT_DOMAIN = "warehouse-forklift"
YEAR = re.compile(r"\b20\d{2}\b")


def _pack_folders() -> list[Path]:
    return sorted(p for p in PACKS_ROOT.iterdir() if p.is_dir())


def _json_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in [str(k), *_json_strings(v)]]
    if isinstance(value, list):
        return [s for v in value for s in _json_strings(v)]
    return [str(value)]


def test_the_pack_folders_are_exactly_the_seven_declared_packs() -> None:
    assert {p.name for p in _pack_folders()} == EXPECTED_PACKS


@pytest.mark.parametrize("name", sorted(EXPECTED_PACKS))
def test_every_pack_folder_loads(name: str) -> None:
    pack = load_pack(PACKS_ROOT / name)
    assert pack.rules


def test_load_packs_loads_all_seven() -> None:
    assert len(load_packs(PACKS_ROOT)) == len(EXPECTED_PACKS)


def test_domains_are_exactly_sim_racing_and_warehouse_forklift() -> None:
    assert {pack.domain for pack in load_packs(PACKS_ROOT)} == {"sim-racing", FORKLIFT_DOMAIN}


def test_forklift_rule_ids_are_unique_across_the_four_packs() -> None:
    packs = load_packs(PACKS_ROOT, domain=FORKLIFT_DOMAIN)
    assert len(packs) == 4
    ids = [rule.id for pack in packs for rule in pack.rules]
    assert len(ids) == len(set(ids))


def test_forklift_packs_opt_in_to_unique_ids_across_domain() -> None:
    for pack in load_packs(PACKS_ROOT, domain=FORKLIFT_DOMAIN):
        assert pack.unique_ids_across_domain is True, pack.name


def test_every_forklift_rule_cites_a_1910_178_clause() -> None:
    for pack in load_packs(PACKS_ROOT, domain=FORKLIFT_DOMAIN):
        for rule in pack.rules:
            assert rule.source_clause is not None, f"{pack.name}/{rule.id}"
            assert rule.source_clause.startswith("1910.178("), f"{pack.name}/{rule.id}"


def test_every_forklift_rule_has_an_on_video_line() -> None:
    for pack in load_packs(PACKS_ROOT, domain=FORKLIFT_DOMAIN):
        for rule in pack.rules:
            lines = rule.text.split("\n")
            assert any(line.startswith("On video:") for line in lines), f"{pack.name}/{rule.id}"


@pytest.mark.parametrize("name", sorted(EXPECTED_PACKS))
def test_no_pack_json_value_holds_a_year_or_a_php_file_name(name: str) -> None:
    data = json.loads((PACKS_ROOT / name / "pack.json").read_text(encoding="utf-8"))
    for value in _json_strings(data):
        assert not YEAR.search(value), f"{name}/pack.json holds a year: {value!r}"
        assert ".php" not in value, f"{name}/pack.json names a .php file: {value!r}"
