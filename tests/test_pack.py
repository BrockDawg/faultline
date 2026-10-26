"""Tests for the rules pack loader in `faultline.pack`."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from faultline.pack import Pack, PackError, Rule, load_pack, load_packs

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOOD_PACK = FIXTURES / "good-pack"
ONE_RULE_PACK = FIXTURES / "one-rule-pack"

RULE_BODY = "Signal before turning.\n\nSource: 1910.178(n)(4)\n"


def write_pack_json(folder: Path, **fields: object) -> None:
    data: dict[str, object] = {"name": folder.name, "version": "1.0.0", "domain": "test-domain"}
    data.update(fields)
    (folder / "pack.json").write_text(json.dumps(data), encoding="utf-8")


def write_rule(folder: Path, file_name: str, rule_id: str, body: str = RULE_BODY) -> Path:
    path = folder / file_name
    path.write_bytes(f"---\nid: {rule_id}\ntitle: Rule {rule_id}\n---\n{body}".encode())
    return path


def make_pack(root: Path, name: str, rule_ids: tuple[str, ...] = ("r1",), **fields: object) -> Path:
    folder = root / name
    folder.mkdir(parents=True)
    write_pack_json(folder, **fields)
    for index, rule_id in enumerate(rule_ids, start=1):
        write_rule(folder, f"{index:02d}-{rule_id}.md", rule_id)
    return folder


def assert_pack_error(folder: Path, *needles: str) -> str:
    with pytest.raises(PackError) as caught:
        load_pack(folder)
    message = str(caught.value)
    for needle in needles:
        assert needle in message, f"{needle!r} not in {message!r}"
    return message


# --- good packs ---------------------------------------------------------------------------


def test_good_pack_loads_its_rules_in_file_name_order() -> None:
    pack = load_pack(GOOD_PACK)
    assert isinstance(pack, Pack)
    assert (pack.name, pack.version, pack.domain) == ("good-pack", "1.0.0", "test-domain")
    assert pack.source == "Test fixture rules"
    assert [rule.id for rule in pack.rules] == ["zebra_first", "alpha_second", "middle_third"]
    assert pack.rules[0].title == "The first rule by file name"
    assert pack.unique_ids_across_domain is False


def test_pack_and_rule_are_frozen_and_rules_is_a_tuple() -> None:
    pack = load_pack(GOOD_PACK)
    assert isinstance(pack.rules, tuple)
    assert all(isinstance(rule, Rule) for rule in pack.rules)
    with pytest.raises(AttributeError):
        pack.name = "changed"  # type: ignore[misc]
    with pytest.raises(AttributeError):
        pack.rules[0].id = "changed"  # type: ignore[misc]


def test_a_string_path_loads_the_same_pack_as_a_path() -> None:
    assert load_pack(str(GOOD_PACK)) == load_pack(GOOD_PACK)


def test_rule_text_is_kept_whole_including_the_source_line() -> None:
    rule = load_pack(GOOD_PACK).rules[0]
    assert rule.text == (
        "Keep the lane clear while another vehicle passes.\n\n"
        "On video: A vehicle stops in the lane.\n\n"
        "Source: 1910.178(m)(1)"
    )


def test_source_clause_is_parsed_and_stripped() -> None:
    rules = load_pack(GOOD_PACK).rules
    assert rules[0].source_clause == "1910.178(m)(1)"
    assert rules[2].source_clause == "Section 4.2"


def test_source_clause_is_none_when_the_text_has_no_source_line() -> None:
    assert load_pack(GOOD_PACK).rules[1].source_clause is None


def test_pack_without_source_has_source_none() -> None:
    assert load_pack(ONE_RULE_PACK).source is None


def test_cold_start_pack_with_exactly_one_rule_loads() -> None:
    pack = load_pack(ONE_RULE_PACK)
    assert pack.rules == (Rule("only_rule", "The only rule", "Stop at the line.", None),)


def test_unique_ids_flag_is_read_from_pack_json(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "flagged", unique_ids_across_domain=True)
    assert load_pack(folder).unique_ids_across_domain is True


def test_bom_rule_file_and_bom_pack_json_load(tmp_path: Path) -> None:
    folder = tmp_path / "bom-pack"
    folder.mkdir()
    meta = json.dumps({"name": "bom-pack", "version": "1.0.0", "domain": "test-domain"})
    (folder / "pack.json").write_bytes(b"\xef\xbb\xbf" + meta.encode("utf-8"))
    (folder / "01-bom.md").write_bytes(
        b"\xef\xbb\xbf---\nid: bom_rule\ntitle: A BOM rule\n---\nStop at the line.\n"
    )
    pack = load_pack(folder)
    assert pack.name == "bom-pack"
    assert pack.rules[0].id == "bom_rule"
    assert pack.rules[0].text == "Stop at the line."


def test_crlf_rule_file_loads_with_the_same_text_as_its_lf_twin(tmp_path: Path) -> None:
    lf_text = (
        "---\nid: twin\ntitle: Twin rule\n---\n"
        "First line of the rule.\n\nOn video: something happens.\n\nSource: 1910.178(o)(6)\n"
    )
    lf_pack = tmp_path / "lf"
    crlf_pack = tmp_path / "crlf"
    for folder in (lf_pack, crlf_pack):
        folder.mkdir()
        write_pack_json(folder)
    (lf_pack / "01-twin.md").write_bytes(lf_text.encode("utf-8"))
    crlf_bytes = lf_text.replace("\n", "\r\n").encode("utf-8")
    assert b"\r\n" in crlf_bytes
    (crlf_pack / "01-twin.md").write_bytes(crlf_bytes)
    lf_rule = load_pack(lf_pack).rules[0]
    crlf_rule = load_pack(crlf_pack).rules[0]
    assert crlf_rule == lf_rule
    assert "\r" not in crlf_rule.text
    assert crlf_rule.source_clause == "1910.178(o)(6)"


def test_mixed_line_endings_load_and_return_lf_text(tmp_path: Path) -> None:
    folder = tmp_path / "mixed"
    folder.mkdir()
    write_pack_json(folder)
    (folder / "01-mixed.md").write_bytes(
        b"---\r\nid: mixed\ntitle: Mixed rule\r\n---\nLine one.\r\nLine two.\n"
    )
    rule = load_pack(folder).rules[0]
    assert rule.text == "Line one.\nLine two."


def test_blank_lines_in_the_header_are_allowed_and_extra_keys_ignored(tmp_path: Path) -> None:
    folder = tmp_path / "spaced"
    folder.mkdir()
    write_pack_json(folder)
    (folder / "01-spaced.md").write_text(
        "---\n\nid: spaced\n\ntitle: Spaced rule\nextra: ignored\n---\nText.\n", encoding="utf-8"
    )
    assert load_pack(folder).rules[0] == Rule("spaced", "Spaced rule", "Text.", None)


# --- errors: one test per error in the contract ---------------------------------------------


def test_missing_folder_is_refused(tmp_path: Path) -> None:
    assert_pack_error(tmp_path / "nowhere", "nowhere", "does not exist")


def test_a_file_path_is_refused_as_not_a_folder(tmp_path: Path) -> None:
    path = tmp_path / "pack.txt"
    path.write_text("x", encoding="utf-8")
    assert_pack_error(path, "pack.txt", "not a folder")


def test_folder_without_rule_files_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()
    write_pack_json(folder)
    assert_pack_error(folder, "empty", "no *.md rule files")


def test_folder_without_pack_json_is_refused(tmp_path: Path) -> None:
    folder = tmp_path / "no-meta"
    folder.mkdir()
    write_rule(folder, "01-r.md", "r")
    assert_pack_error(folder, "no-meta", "no pack.json")


def test_pack_json_that_is_not_valid_json_is_refused(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "bad-json")
    (folder / "pack.json").write_text("{not json", encoding="utf-8")
    assert_pack_error(folder, "pack.json", "not valid JSON")


def test_pack_json_that_is_not_an_object_is_refused(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "list-json")
    (folder / "pack.json").write_text('["a", "b"]', encoding="utf-8")
    assert_pack_error(folder, "pack.json", "must hold a JSON object")


@pytest.mark.parametrize("field", ["name", "version", "domain"])
def test_pack_json_missing_a_required_field_is_refused(tmp_path: Path, field: str) -> None:
    folder = make_pack(tmp_path, "missing")
    data = json.loads((folder / "pack.json").read_text(encoding="utf-8"))
    del data[field]
    (folder / "pack.json").write_text(json.dumps(data), encoding="utf-8")
    assert_pack_error(folder, "pack.json", repr(field), "missing")


@pytest.mark.parametrize("value", ["", "   ", 7, None])
def test_pack_json_with_a_blank_or_non_string_field_is_refused(
    tmp_path: Path, value: object
) -> None:
    folder = make_pack(tmp_path, "blank", version=value)
    assert_pack_error(folder, "pack.json", "'version'", "non-empty string")


def test_pack_json_with_a_non_string_source_is_refused(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "bad-source", source=["a"])
    assert_pack_error(folder, "pack.json", "'source'", "must be a string")


@pytest.mark.parametrize("value", ["true", 1, None, "yes"])
def test_unique_ids_flag_that_is_not_a_bool_is_refused(tmp_path: Path, value: object) -> None:
    folder = make_pack(tmp_path, "bad-flag", unique_ids_across_domain=value)
    assert_pack_error(folder, "pack.json", "unique_ids_across_domain", "true or false")


def test_rule_file_not_opening_with_a_fence_is_refused(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "no-open")
    (folder / "01-r1.md").write_text("id: r1\ntitle: T\n---\nText.\n", encoding="utf-8")
    assert_pack_error(folder, "01-r1.md", "must open with a '---' line")


def test_rule_file_without_a_closing_fence_is_refused(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "no-close")
    (folder / "01-r1.md").write_text("---\nid: r1\ntitle: T\n", encoding="utf-8")
    assert_pack_error(folder, "01-r1.md", "no closing '---'")


def test_header_line_without_a_colon_is_refused(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "no-colon")
    (folder / "01-r1.md").write_text(
        "---\nid: r1\ntitle: T\nnot a pair\n---\nText.\n", encoding="utf-8"
    )
    assert_pack_error(folder, "01-r1.md", "'not a pair'", "has no ':'")


@pytest.mark.parametrize("key", ["id", "title"])
def test_header_missing_id_or_title_is_refused(tmp_path: Path, key: str) -> None:
    folder = make_pack(tmp_path, "missing-key")
    other = "title: T" if key == "id" else "id: r1"
    (folder / "01-r1.md").write_text(f"---\n{other}\n---\nText.\n", encoding="utf-8")
    assert_pack_error(folder, "01-r1.md", f"no {key!r}")


@pytest.mark.parametrize("key", ["id", "title"])
def test_header_with_blank_id_or_title_is_refused(tmp_path: Path, key: str) -> None:
    folder = make_pack(tmp_path, "blank-key")
    header = "id:   \ntitle: T" if key == "id" else "id: r1\ntitle:"
    (folder / "01-r1.md").write_text(f"---\n{header}\n---\nText.\n", encoding="utf-8")
    assert_pack_error(folder, "01-r1.md", f"{key!r} is blank")


def test_rule_file_with_no_text_after_the_header_is_refused(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "no-text")
    (folder / "01-r1.md").write_text("---\nid: r1\ntitle: T\n---\n\n  \n", encoding="utf-8")
    assert_pack_error(folder, "01-r1.md", "no rule text after the header")


def test_duplicate_id_in_one_pack_is_refused_naming_both_files(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "dupes", rule_ids=("same",))
    write_rule(folder, "02-again.md", "same")
    assert_pack_error(folder, "dupes", "'same'", "01-same.md", "02-again.md", "twice")


def test_rule_file_that_is_not_utf8_is_refused(tmp_path: Path) -> None:
    folder = make_pack(tmp_path, "latin")
    (folder / "01-r1.md").write_bytes(b"---\nid: r1\ntitle: Caf\xe9\n---\nText.\n")
    assert_pack_error(folder, "01-r1.md", "not valid UTF-8")


# --- load_packs ------------------------------------------------------------------------------


def test_load_packs_returns_every_pack_folder_sorted_by_folder_name(tmp_path: Path) -> None:
    make_pack(tmp_path, "zulu")
    make_pack(tmp_path, "alpha")
    make_pack(tmp_path, "mike")
    (tmp_path / "not-a-pack").mkdir()
    (tmp_path / "README.md").write_text("Packs live here.\n", encoding="utf-8")
    assert [pack.name for pack in load_packs(tmp_path)] == ["alpha", "mike", "zulu"]


def test_load_packs_accepts_a_string_root(tmp_path: Path) -> None:
    shutil.copytree(GOOD_PACK, tmp_path / "good-pack")
    assert load_packs(str(tmp_path)) == (load_pack(GOOD_PACK),)


def test_load_packs_filters_by_domain(tmp_path: Path) -> None:
    make_pack(tmp_path, "a-racing", domain="sim-racing")
    make_pack(tmp_path, "b-forklift", domain="warehouse-forklift")
    make_pack(tmp_path, "c-racing", domain="sim-racing")
    assert [p.name for p in load_packs(tmp_path, domain="sim-racing")] == ["a-racing", "c-racing"]
    assert [p.name for p in load_packs(tmp_path, domain="warehouse-forklift")] == ["b-forklift"]
    assert load_packs(tmp_path, domain="nothing") == ()


def test_load_packs_on_an_empty_root_returns_nothing(tmp_path: Path) -> None:
    assert load_packs(tmp_path) == ()


def test_load_packs_refuses_a_missing_root(tmp_path: Path) -> None:
    with pytest.raises(PackError, match="does not exist"):
        load_packs(tmp_path / "nowhere")


def test_load_packs_refuses_a_root_that_is_a_file(tmp_path: Path) -> None:
    path = tmp_path / "packs.txt"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(PackError, match="not a folder"):
        load_packs(path)


def test_shared_ids_across_unflagged_packs_are_allowed(tmp_path: Path) -> None:
    make_pack(tmp_path, "oval-like", rule_ids=("conduct_general", "a"), domain="sim-racing")
    make_pack(tmp_path, "road-like", rule_ids=("conduct_general", "b"), domain="sim-racing")
    assert len(load_packs(tmp_path)) == 2


def test_shared_id_across_flagged_packs_of_one_domain_is_refused(tmp_path: Path) -> None:
    make_pack(tmp_path, "pack-one", rule_ids=("shared", "x"), unique_ids_across_domain=True)
    make_pack(tmp_path, "pack-two", rule_ids=("y", "shared"), unique_ids_across_domain=True)
    with pytest.raises(PackError) as caught:
        load_packs(tmp_path)
    message = str(caught.value)
    for needle in ("'shared'", "pack-one", "pack-two", "test-domain"):
        assert needle in message


def test_shared_id_with_only_one_pack_flagged_is_allowed(tmp_path: Path) -> None:
    make_pack(tmp_path, "pack-one", rule_ids=("shared",), unique_ids_across_domain=True)
    make_pack(tmp_path, "pack-two", rule_ids=("shared",))
    assert len(load_packs(tmp_path)) == 2


def test_shared_id_across_flagged_packs_of_different_domains_is_allowed(tmp_path: Path) -> None:
    make_pack(tmp_path, "pack-one", ("shared",), domain="d1", unique_ids_across_domain=True)
    make_pack(tmp_path, "pack-two", ("shared",), domain="d2", unique_ids_across_domain=True)
    assert len(load_packs(tmp_path)) == 2


def test_load_packs_passes_on_a_bad_pack_error(tmp_path: Path) -> None:
    make_pack(tmp_path, "good")
    broken = make_pack(tmp_path, "broken")
    (broken / "pack.json").write_text("{", encoding="utf-8")
    with pytest.raises(PackError, match="broken"):
        load_packs(tmp_path)
