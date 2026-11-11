"""Tests for the protest reader and normaliser. Every name here is invented."""

from __future__ import annotations

import dataclasses
import gzip
import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest

from faultline import lint
from faultline.adapters.pitbot.protest import (
    OUTCOME_KEYS,
    OUTCOME_WORD,
    REPORT_KEYS,
    UNRESOLVED_DRIVER,
    Normalised,
    ProtestError,
    _name_spans,
    _Names,
    normalise,
    read_reports,
)

SESSION = "11112222/RACE"
NAMES = {
    "01": "Quentin Ravelstone",
    "7": "Marisol Brackenfeld",
    "26": "Odile Vantongeren",
    "70": "Ignatius Throckwold",
}
OUTSIDER = "Leopold Starkweather"
ALL_NAMES = [*NAMES.values(), OUTSIDER]
CUST = {"01": 5001, "7": 5007, "26": 5026, "70": 5070}
NUMBER_MAP = {
    "entries": [
        {
            "cust_id": "5001",
            "league_num": "899",
            "rule": "season_one",
            "sim_nums": {SESSION: "01", "99990000/RACE": "899"},
        },
        {
            "cust_id": "5070",
            "league_num": "170",
            "rule": "season_one",
            "sim_nums": {SESSION: "70"},
        },
        {
            "cust_id": "6000",
            "league_num": "333",
            "rule": "season_one",
            "sim_nums": {"99990000/RACE": "08"},
        },
    ]
}


class StubFeed:
    """Exactly the four members `normalise` may read."""

    def __init__(self, session: str = SESSION, names: Mapping[str, str] = NAMES) -> None:
        self._session = session
        self._names = dict(names)

    @property
    def session(self) -> str:
        return self._session

    @property
    def nums(self) -> list[str]:
        return list(self._names)

    def cust_id(self, num: str) -> int | None:
        return CUST.get(num)

    def private_names(self) -> dict[str, str]:
        return dict(self._names)


def report(description: str, involved: str | None = None, reporter: str | None = None) -> dict:
    return {
        "created_at": "2026-01-01 00:00:00",
        "description": description,
        "id": 7,
        "involved": involved,
        "iracing_subsession_id": "11112222",
        "race_number": None,
        "reporter_car": reporter,
        "session": SESSION,
        "track": "Test Circuit",
    }


def run(description: str, involved: str | None = None, reporter: str | None = None) -> Normalised:
    return normalise(
        report(description, involved, reporter), StubFeed(), NUMBER_MAP, known_names=[OUTSIDER]
    )


def name_bits() -> set[str]:
    bits = {n.casefold() for n in ALL_NAMES}
    bits |= lint.name_tokens(ALL_NAMES)
    return bits


def assert_no_name(n: Normalised) -> None:
    for field in dataclasses.fields(n):
        value = json.dumps(getattr(n, field.name)).casefold()
        for bit in name_bits():
            assert bit not in value, f"a name survived in field {field.name}"


# ---------------------------------------------------------------- names


def test_full_names_in_description_and_involved_become_cars() -> None:
    n = run(
        "Quentin Ravelstone turned in on Marisol Brackenfeld at turn 3.",
        involved="Odile Vantongeren; Ignatius Throckwold",
    )
    assert "car 01 turned in on car 7" in n.text
    assert n.text.endswith("Involved: car 26; car 70")
    assert n.cars == ("01", "7", "26", "70")
    assert n.unresolved == ()
    assert_no_name(n)


def test_surname_only_and_lower_case_names_are_replaced() -> None:
    n = run(
        "Ravelstone hit brackenfeld's rear at Brackenfeld corner, then VANTONGEREN spun. "
        "later ravelstone apologised, and Quentin waved."
    )
    assert n.text.startswith(
        "car 01 hit car 7's rear at car 7 corner, then car 26 spun. "
        "later car 01 apologised, and car 01 waved."
    )
    assert_no_name(n)


def test_lower_case_lone_name_never_written_capitalised_is_never_a_car() -> None:
    # A lone token must be written capitalised somewhere to resolve. A 4+ letter one that
    # never is gets masked (the lint would refuse it), and adds no car.
    n = run("ravelstone hit me.")
    assert n.text == f"{UNRESOLVED_DRIVER} hit me."
    assert n.cars == ()


def test_ordinary_word_that_is_a_name_token_is_left_alone() -> None:
    names = _Names({**NAMES, "9": "Ysolde Straight"}, [])
    lower = _name_spans("braked on the main straight.", names, ())
    assert [s[2] for s in lower] == [UNRESOLVED_DRIVER]  # masked, never re-pinned to car 9
    text = "Straight braked on the main straight."
    assert [s[2] for s in _name_spans(text, names, ())] == ["car 9", "car 9"]
    # The caller's allow list keeps the word out of the lint too.
    n = normalise(
        report("Car 7 braked on the main straight."),
        StubFeed(names={**NAMES, "9": "Ysolde Straight"}),
        NUMBER_MAP,
        allow=["straight"],
    )
    assert n.text == "car 7 braked on the main straight."
    assert n.unresolved == ()


def test_name_beside_its_number_reads_once() -> None:
    n = run("Contact with Odile Vantongeren #26 into turn 1.")
    assert "Contact with car 26 into turn 1." in n.text


def test_known_name_outside_the_session_is_unresolved() -> None:
    n = run("Leopold Starkweather and then starkweather again pushed me wide.")
    assert n.text.count(UNRESOLVED_DRIVER) == 2
    assert n.unresolved == (UNRESOLVED_DRIVER, UNRESOLVED_DRIVER)
    assert n.cars == ()
    assert_no_name(n)


def test_token_shared_by_two_drivers_is_unresolved() -> None:
    names = {**NAMES, "9": "Quentin Hollowmere"}
    n = normalise(report("Quentin dived in late."), StubFeed(names=names), NUMBER_MAP)
    assert n.text == f"{UNRESOLVED_DRIVER} dived in late."
    assert n.cars == ()


def test_lone_first_name_held_by_someone_outside_the_session_is_unresolved() -> None:
    known = [OUTSIDER, "Quentin Hollowmere"]
    n = normalise(report("Quentin dived in late."), StubFeed(), NUMBER_MAP, known_names=known)
    assert n.text == f"{UNRESOLVED_DRIVER} dived in late."
    assert n.cars == ()
    # The full name is still car 01: every token in the mention is car 01's.
    n = normalise(
        report("Quentin Ravelstone dived in late."), StubFeed(), NUMBER_MAP, known_names=known
    )
    assert n.text == "car 01 dived in late."


def test_lone_surname_held_by_another_person_is_unresolved() -> None:
    known = ["Horatio Ravelstone"]
    n = normalise(report("Ravelstone dived in."), StubFeed(), NUMBER_MAP, known_names=known)
    assert n.text == f"{UNRESOLVED_DRIVER} dived in."
    # The same person written another way (a subset of the name) is not someone else.
    n = normalise(
        report("Ravelstone dived in."), StubFeed(), NUMBER_MAP, known_names=["Ravelstone"]
    )
    assert n.text == "car 01 dived in."


def test_mention_mixing_two_drivers_is_unresolved_and_adds_no_car() -> None:
    n = run("Then Quentin Brackenfeld hit me.")
    assert n.text == f"Then {UNRESOLVED_DRIVER} hit me."
    assert n.cars == ()


def test_unknown_capitalised_word_inside_a_mention_makes_it_unresolved() -> None:
    n = run("I was hit by Zorbo Ravelstone at the hairpin.")
    assert n.text == f"I was hit by {UNRESOLVED_DRIVER} at the hairpin."
    assert n.cars == ()


def test_sentence_start_word_does_not_join_a_mention() -> None:
    n = run("Then Ravelstone hit me. Afterwards Vantongeren spun.")
    assert n.text == "Then car 01 hit me. Afterwards car 26 spun."


def test_short_first_name_and_shared_prefix_tag() -> None:
    tagged = {
        "01": "XQV Ada Ravelstone",
        "7": "XQV Marisol Brackenfeld",
        "26": "XQV Odile Vantongeren",
        "70": "XQV Ignatius Throckwold",
    }
    n = normalise(
        report(
            "Ada Ravelstone hit Marisol at turn 2. Then ada ravelstone again, "
            "and XQV Odile Vantongeren saw it.",
            involved="XQV Ada Ravelstone",
        ),
        StubFeed(names=tagged),
        NUMBER_MAP,
    )
    assert n.text == (
        "car 01 hit car 7 at turn 2. Then car 01 again, and car 26 saw it.\nInvolved: car 01"
    )
    assert n.cars == ("01", "7", "26")
    for bit in ("ada", "xqv", "ravelstone", "marisol"):
        assert not re.search(r"(?<!\w)" + bit + r"(?!\w)", n.text, re.IGNORECASE)


def test_a_real_number_from_another_session_is_never_snapped() -> None:
    names = {"91": "Ysolde Marchbank", "7": "Marisol Brackenfeld", "01": "Quentin Ravelstone"}
    feed = StubFeed(names={k: v for k, v in names.items() if k != "01"})
    n = normalise(report("#01 came across."), feed, NUMBER_MAP)
    assert n.text == "car [unresolved 01] came across."
    assert n.cars == ()
    # 08 is a sim number only in another session; 01 is one edit away but must not catch it.
    n = normalise(report("#08 came across."), StubFeed(), NUMBER_MAP)
    assert n.text == "car [unresolved 08] came across."


def test_feed_name_with_a_digit_suffix_matches_the_plain_name() -> None:
    names = {**NAMES, "26": "Odile Vantongeren2"}
    n = normalise(
        report("Odile Vantongeren cut across."),
        StubFeed(names=names),
        NUMBER_MAP,
        known_names=["Odile Vantongeren"],
    )
    assert n.text == "car 26 cut across."
    assert n.unresolved == ()


def test_links_and_word_slashes_pass_the_lint() -> None:
    n = run("Clip: https://example.org/v?x=1 shows brake/steering lock and lap 3/4.")
    assert n.text == "Clip: [link] shows brake / steering lock and lap 3/4."
    assert n.laps == (3, 4)


# ---------------------------------------------------------------- numbers


def test_number_patterns() -> None:
    n = run("#7 hit Car 26, then car 70 and Nr. 01 and No. 7 touched.")
    assert n.text == "car 7 hit car 26, then car 70 and car 01 and car 7 touched."
    assert n.cars == ("01", "7", "26", "70")


def test_league_number_maps_to_sim_number_in_this_session() -> None:
    n = run("#899 locked up into turn 2 and car 170 went wide.", reporter="899")
    assert n.text == "car 01 locked up into turn 2 and car 70 went wide."
    assert n.cars == ("01", "70")
    assert n.reporter_car == "01"


def test_sim_number_reads_as_itself_first() -> None:
    n = run("Car 7 was the one.", reporter="26")
    assert n.cars == ("7",)
    assert n.reporter_car == "26"


def test_unresolved_number_is_listed() -> None:
    n = run("#58 came across and car 26 had nowhere to go.", reporter="44")
    assert n.text == "car [unresolved 58] came across and car 26 had nowhere to go."
    assert n.unresolved == ("car [unresolved 44]", "car [unresolved 58]")
    assert n.reporter_car is None
    assert n.cars == ("26",)


def test_a_clear_misread_snaps_but_a_real_entry_never_moves() -> None:
    assert run("car 260 dived in.").cars == ("26",)
    # 333 is a league number in another session: real, so it is never re-pinned.
    n = run("car 333 dived in.")
    assert n.cars == ()
    assert n.unresolved == ("car [unresolved 333]",)


def test_league_number_whose_cust_id_disagrees_is_not_mapped() -> None:
    bad = {"entries": [{**NUMBER_MAP["entries"][0], "cust_id": "9999"}]}
    n = normalise(report("#899 hit me."), StubFeed(), bad)
    assert n.cars == ()
    assert n.unresolved == ("car [unresolved 899]",)


# ---------------------------------------------------------------- laps and words


@pytest.mark.parametrize(
    ("text", "laps", "last"),
    [
        ("on lap 5 at the hairpin", (5,), False),
        ("Lap 12, turn 3", (12,), False),
        ("laps 3 & 4 he blocked", (3, 4), False),
        ("laps 6 and 8", (6, 8), False),
        ("L7 into turn 1", (7,), False),
        ("L 9 at the chicane", (9,), False),
        ("last lap, final corner", (), True),
        ("last lap after the lap 2 clash", (2,), True),
        ("collapse at turn 4", (), False),
    ],
)
def test_lap_patterns(text: str, laps: tuple[int, ...], last: bool) -> None:
    n = run(text)
    assert n.laps == laps
    assert n.last_lap is last


def test_outcome_words_are_redacted() -> None:
    n = run(
        "He deserves a penalty. Penalties exist. He was penalised before, penalized again; "
        "no action last time, and the ruling was ruled wrong."
    )
    for word in ("penalt", "penalis", "penaliz", "no action", "ruling", "ruled"):
        assert word not in n.text.casefold()
    assert n.text.count(OUTCOME_WORD) == 7


# ---------------------------------------------------------------- refusals and shape


def test_feed_for_another_session_is_refused() -> None:
    with pytest.raises(ProtestError, match="not the report's session"):
        normalise(report("x"), StubFeed(session="99990000/RACE"), NUMBER_MAP)


def test_short_session_name_on_the_feed_is_accepted() -> None:
    n = normalise(report("Car 7 hit me."), StubFeed(session="RACE"), NUMBER_MAP)
    assert n.session == SESSION


def test_lint_failure_never_echoes_the_text() -> None:
    with pytest.raises(ProtestError) as info:
        run("the clip is in C:\\clips\\race and/or elsewhere")
    assert "clips" not in str(info.value)
    assert "lint" in str(info.value)


def test_normalised_holds_no_outcome_field() -> None:
    fields = {f.name for f in dataclasses.fields(Normalised)}
    banned = {*OUTCOME_KEYS, "penalty", "offender", "victim", "decision", "name", "names"}
    assert not fields & banned
    assert fields == {
        "id",
        "session",
        "text",
        "cars",
        "reporter_car",
        "laps",
        "last_lap",
        "unresolved",
    }
    with pytest.raises(dataclasses.FrozenInstanceError):
        run("x").text = "y"  # type: ignore[misc]


def _write_lines(path: Path, rows: Iterable[dict]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def test_read_reports_reads_contract_lines(tmp_path: Path) -> None:
    rows = [report("one"), report("two")]
    got = read_reports(_write_lines(tmp_path / "reports.jsonl", rows))
    assert [r["description"] for r in got] == ["one", "two"]
    assert set(got[0]) == set(REPORT_KEYS)


@pytest.mark.parametrize("key", OUTCOME_KEYS)
def test_read_reports_refuses_an_outcome_key(tmp_path: Path, key: str) -> None:
    rows = [report("one"), {**report("two"), key: "x"}]
    path = _write_lines(tmp_path / "reports.jsonl", rows)
    with pytest.raises(ProtestError) as info:
        read_reports(path)
    message = str(info.value)
    assert "reports.jsonl" in message
    assert "line 2" in message
    assert repr(key) in message


def test_read_reports_refuses_missing_and_extra_keys(tmp_path: Path) -> None:
    row = report("one")
    del row["track"]
    with pytest.raises(ProtestError, match="missing"):
        read_reports(_write_lines(tmp_path / "a.jsonl", [row]))
    with pytest.raises(ProtestError, match="unexpected"):
        read_reports(_write_lines(tmp_path / "b.jsonl", [{**report("x"), "extra": 1}]))


# ---------------------------------------------------------------- the real reports


REPO = Path(__file__).resolve().parents[2]
RACING = REPO / "data" / "racing"


def _clean(name: str | None) -> str:
    if not name or name == "NULL":
        return ""
    name = name.replace("\\n", " ")
    name = re.sub(r"#\s*\d+|\b\d+\b", " ", name)
    name = re.sub(r"[^\w' .-]+", " ", name)
    return " ".join(name.split()).strip(" .-'")


def _tsv_rows(path: Path) -> list[dict[str, str]]:
    text = path.read_bytes().decode("utf-8", errors="replace")
    lines = [ln.rstrip("\r") for ln in text.split("\n") if ln.strip()]
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"), strict=False)) for ln in lines[1:]]


def _all_names(inputs: dict, league: dict) -> list[str]:
    """Every name the public-tree sweep knows, read in memory only."""
    names: set[str] = set()
    for feed in sorted({s["feed"] for s in league["sessions"].values()}):
        with gzip.open(feed, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    frame = json.loads(line)
                    for item in (frame.get("rows") or []) + (frame.get("positions") or []):
                        names.add(_clean(item.get("name")))
    for row in _tsv_rows(Path(inputs["incidents_tsv"])):
        names.add(_clean(row.get("reporter_name")))
        names.add(_clean(row.get("penalised")))
        for part in re.split(r"[;\n]|\\n|\band\b|&|,", row.get("involved") or ""):
            names.add(_clean(part))
    stats = Path(inputs["replays_dir"]).parent / "iracing_driver_stats.tsv"
    if stats.is_file():
        for row in _tsv_rows(stats):
            names.add(_clean(row.get("name")))
    return sorted(n for n in names if n)


@pytest.mark.private
def test_real_reports_normalise_clean() -> None:
    if not (RACING / "reports.jsonl").is_file() or not (RACING / "inputs.json").is_file():
        pytest.skip("private racing data absent")
    try:
        from faultline.adapters.pitbot.feed import Feed  # type: ignore[attr-defined]
    except ImportError:
        pytest.skip("feed.py is not built yet")
    inputs = json.loads((RACING / "inputs.json").read_text(encoding="utf-8"))
    league = json.loads((RACING / "league.json").read_text(encoding="utf-8"))
    names = _all_names(inputs, league)
    bits = {n.casefold() for n in names if " " in n} | lint.name_tokens(names)
    reports = read_reports(RACING / "reports.jsonl")
    assert len(reports) == 10
    for rep in reports:
        sess = league["sessions"][rep["session"]]
        feed = Feed.load(sess["feed"], sess["session"])
        n = normalise(rep, feed, league["number_map"], known_names=names)
        lint.assert_clean(n.text, names=names)
        values = json.dumps(list(dataclasses.asdict(n).values())).casefold()
        leaked = sum(
            1 for bit in bits if re.search(r"(?<!\w)" + re.escape(bit) + r"(?!\w)", values)
        )
        assert leaked == 0, f"report {n.id}: {leaked} name piece(s) survived"
        # Every name token of 2 or more letters, from the feed's names and the full list.
        short = {m.group().casefold() for nm in names for m in re.finditer(r"[^\W\d_]{2,}", nm)}
        for nm in feed.private_names().values():
            short |= {m.group().casefold() for m in re.finditer(r"[^\W\d_]{2,}", nm or "")}
        bare = re.sub(
            r"car (?:\[unresolved \w+\]|\w+)|\[unresolved driver\]|\[outcome word\]|\[link\]"
            r"|^Involved:",
            " ",
            n.text,
            flags=re.MULTILINE,
        )
        text_tokens = [m.group().casefold() for m in re.finditer(r"[^\W\d_]{2,}", bare)]
        short_left = sum(1 for t in text_tokens if t in short)
        assert short_left == 0, f"report {n.id}: {short_left} name token(s) of 2+ letters left"
        print(
            f"report {n.id}: cars {len(n.cars)}, laps {len(n.laps)}"
            f"{' +last' if n.last_lap else ''}, unresolved {len(n.unresolved)}"
        )
