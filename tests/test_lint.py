"""Tests for the leak lint in `faultline.lint`. Every name here is invented."""

from __future__ import annotations

import pytest

from faultline.lint import LintError, assert_clean, lint, name_tokens

NAMES = ("Test Driver A", "Quentin Ravelstone", "Mira Okonkwo-Vale")
SITE = "Harbourline Night Series"

CLEAN = (
    "Entry 12 and entry 47 were within 3.4 metres at second 81.5, closing at 2.1 m/s.\n"
    "The written account says entry 47 moved across late. Rule R2 applies; 3/5 frames agree.\n"
    "Answer with one id from the list: 12, 47."
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Report filed by Quentin Ravelstone after the restart.", ["Quentin Ravelstone"]),
        ("Ravelstone moved across late.", ["Ravelstone"]),
        ("RAVELSTONE moved across late.", ["RAVELSTONE"]),
        ("See C:\\clips\\entry12 for the view.", ["C:\\clips\\entry12"]),
        ("Frame source: second-81.mp4", [".mp4"]),
        ("Look at https://example.invalid/view?id=3 first.", ["https://example.invalid/view?id=3"]),
        ("This is the harbourline night series final.", ["harbourline night series"]),
        ("It was (Ravelstone's) fault, said Okonkwo.", ["Ravelstone", "Okonkwo"]),
        ("Filed by Quentin\nRavelstone today.", ["Quentin\nRavelstone"]),
    ],
    ids=[
        "full-name",
        "surname-alone",
        "surname-other-case",
        "path",
        "extension",
        "url",
        "league-name",
        "glued-to-punctuation",
        "across-line-break",
    ],
)
def test_planted_leak_is_caught(text: str, expected: list[str]) -> None:
    hits = lint(text, NAMES, extra_banned=(SITE,))
    assert set(expected) <= set(hits), hits
    with pytest.raises(LintError):
        assert_clean(text, NAMES, extra_banned=(SITE,))


def test_full_name_across_line_break_also_hits_each_token() -> None:
    hits = lint("Filed by Quentin\nRavelstone today.", NAMES)
    assert hits == ["Quentin", "Quentin\nRavelstone", "Ravelstone"]


def test_path_is_one_hit_per_run() -> None:
    assert lint("See C:\\clips\\entry12 or /srv/a/b.", ()) == ["C:\\clips\\entry12", "/srv/a/b"]


def test_name_token_inside_longer_word_does_not_hit() -> None:
    text = "The Ravelstones and xQuentin and Quentinly and Okonkwovale are not names here."
    assert lint(text, NAMES) == []
    assert_clean(text, NAMES)


def test_clean_prompt_passes() -> None:
    assert lint(CLEAN, NAMES, extra_banned=(SITE,)) == []
    assert_clean(CLEAN, NAMES, extra_banned=(SITE,))


def test_error_message_holds_no_name_and_gives_offsets() -> None:
    text = "Quentin Ravelstone said Okonkwo was at /srv/frames/a.jpg"
    with pytest.raises(LintError) as caught:
        assert_clean(text, NAMES, extra_banned=(SITE,))
    message = str(caught.value)
    folded = message.casefold()
    for token in name_tokens(NAMES) | {"srv", "frames", ".jpg", "harbourline"}:
        assert token not in folded
    assert "Quentin" not in message
    assert caught.value.offsets[0] == 0
    assert f"{len(caught.value.offsets)} banned hit(s)" in message
    assert "name at 0" in message


def test_hits_are_ordered_by_offset_and_deterministic() -> None:
    text = "data/a.mp4 then Ravelstone then www.example.invalid"
    first = lint(text, NAMES)
    assert first == lint(text, list(reversed(NAMES)))
    assert first == ["data/a.mp4", ".mp4", "Ravelstone", "www.example.invalid"]


def test_name_tokens_splits_and_drops_short_tokens() -> None:
    assert name_tokens(NAMES) == {
        "test",
        "driver",
        "quentin",
        "ravelstone",
        "mira",
        "okonkwo",
        "vale",
    }
    assert name_tokens(["Al Bo", "Ana-Lee"]) == set()


def test_allow_lets_a_common_word_through() -> None:
    names = ["Quentin Main", "Ana Account"]
    text = "The main reading is in the account the entry gave."
    assert lint(text, names) == ["main", "account"]
    assert lint(text, names, allow={"Main", "account"}) == []


def test_allow_does_not_allow_the_full_name() -> None:
    names = ["Quentin Main"]
    hits = lint("Quentin Main filed it; the main view.", names, allow={"main"})
    assert hits == ["Quentin", "Quentin Main"]


def test_short_single_name_is_still_banned_as_a_phrase() -> None:
    assert lint("Ana filed it.", ["Ana"]) == ["Ana"]
    assert lint("Ana filed it.", ["Ana"], allow={"ana"}) == []


@pytest.mark.parametrize("text", ["and/or", "/home/x", "d:/runs", "notes.ndjson.gz", "a.jsonl"])
def test_path_and_extension_forms(text: str) -> None:
    assert lint(text, ()) != []


@pytest.mark.parametrize("text", ["2.1 m/s", "30 km/h", "3/5 agree", "second 81.5", "e.g. this"])
def test_units_and_numbers_pass(text: str) -> None:
    assert lint(text, ()) == []


def test_empty_names_and_phrases_are_ignored() -> None:
    assert lint("plain words", ["", "   "], extra_banned=("", " ")) == []


def test_email_is_one_whole_hit() -> None:
    text = "Contact jo.bloggs@example.org."
    assert lint(text, ()) == ["jo.bloggs@example.org"]
    with pytest.raises(LintError) as caught:
        assert_clean(text, ())
    message = str(caught.value)
    assert "email at 8" in message
    assert "bloggs" not in message.casefold()
    assert "example" not in message.casefold()


def test_handle_is_one_whole_hit() -> None:
    text = "Clip posted by @speedy_jo, then reposted."
    assert lint(text, ()) == ["@speedy_jo"]
    with pytest.raises(LintError) as caught:
        assert_clean(text, ())
    message = str(caught.value)
    assert "handle at 15" in message
    assert "speedy" not in message.casefold()


def test_at_inside_a_word_is_not_a_handle() -> None:
    assert lint("score a@b and 5 @ 3", ()) == []


def test_per_person_id_passed_in_extra_banned_is_caught() -> None:
    text = "Report from customer 4410273 about entry 12."
    assert lint(text, NAMES, extra_banned=("4410273",)) == ["4410273"]
    assert lint("Entry 144102739 only.", NAMES, extra_banned=("4410273",)) == []
    with pytest.raises(LintError) as caught:
        assert_clean(text, NAMES, extra_banned=("4410273",))
    assert "4410273" not in str(caught.value)
    assert "banned at 21" in str(caught.value)


# --------------------------------------------------------------- the names-only form

PATH_SHAPES = (
    "Car 7 was crashing/careless at 5.6m/s, closing at -0.7m/s.",
    "Under 9.5/9.5.2 the contact was careless/non-intentional.",
    "Frames 1/2/3 show it; the green/blue car held its line.",
)


@pytest.mark.parametrize("text", PATH_SHAPES)
def test_names_only_lets_path_shapes_through(text: str) -> None:
    assert lint(text, NAMES)  # the full prompt lint still refuses them
    assert lint(text, NAMES, paths=False) == []
    assert_clean(text, NAMES, paths=False)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("Frames 1/2/3 show Test Driver A braking late.", "name"),
        ("Under 9.5/9.5.2 Ravelstone was careless.", "name"),
        ("Write to someone@example.org about 5.6m/s.", "email"),
        ("Ask @someone about frames 1/2/3.", "handle"),
        ("See https://example.invalid/clip for it.", "url"),
        ("This is the harbourline night series at 5.6m/s.", "banned"),
    ],
)
def test_names_only_still_refuses_people(text: str, kind: str) -> None:
    with pytest.raises(LintError) as raised:
        assert_clean(text, NAMES, extra_banned=[SITE], paths=False)
    assert set(raised.value.kinds) == {kind}


@pytest.mark.parametrize("text", ["and/or", "d:/runs", "/home/x", "a.jsonl"])
def test_the_default_is_still_the_full_check(text: str) -> None:
    with pytest.raises(LintError):
        assert_clean(text, NAMES)
    assert lint(text, NAMES, paths=False) == []
