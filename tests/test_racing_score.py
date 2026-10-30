"""scripts/racing_score.py: every mark's pass and fail edge, on a synthetic truth table and preds.

Everything here is made up: sessions 100 and 200 on tracks "Alpha" and "Beta", invented car
numbers, and an invented name in the truth table's `basis` and in the preds' evidence that must
never reach the printed table or score.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "racing_score.py"
sys.path.insert(0, str(SCRIPT.parent))
import racing_score as rs  # noqa: E402

NAME = "Test Driver A"
H1, FE, RA = "100/HEAT 1", "100/FEATURE", "200/RACE"
# id: (session, offender, victim, contact_te, duplicate_of)
TRUTH: dict[str, tuple[str, str, str | None, int | None, str | None]] = {
    "1": (H1, "7", "8", 175, None),
    "11": (RA, "41", "22", 3787, None),
    "13": (RA, "44", "26", 1387, None),
    "14": (RA, "70", "32", 533, "15"),
    "15": (RA, "70", "32", 533, None),
    "16": (H1, "68", "18", 299, None),
    "18": (H1, "5", None, None, None),
    "23": (FE, "12", "18", 2471, "24"),
    "24": (FE, "12", "18", 2471, None),
    "46": (FE, "01", "34", 162, None),
}
NOFEED = ("2", "3", "4", "5", "6", "7", "9", "10", "48")
# The incident-limit decisions and the stated totals the catalogue holds for them.
CHECKS = {
    "19": [(H1, 21)],
    "20": [(H1, 31)],
    "22": [(FE, 24)],
    "25": [(RA, 30)],
    "26": [(RA, 26), (FE, 22)],
    "27": [(FE, 23)],
    "28": [(FE, 22)],
}
# Breaching cars: (session, car, total). The last two have no ruling on record.
BREACHES = [
    (H1, "18", 21),
    (H1, "5", 31),
    (FE, "41", 24),
    (RA, "26", 30),
    (RA, "9", 26),
    (FE, "5", 22),
    (FE, "84", 23),
    (RA, "70", 29),
    (FE, "123", 27),
]


def _truth_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": did,
            "session": s,
            "offender_sim": off,
            "victim_sim": vic,
            "contact_te": te,
            "contact_source": None if te is None else "answer_key",
            "duplicate_of": dup,
            "verdict": "penalty",
            "confirmed_by": "a test",
            "basis": f"{NAME} hit car {vic} on lap 3",
        }
        for did, (s, off, vic, te, dup) in TRUTH.items()
    ]


def _const_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": r["id"],
            "session": r["session"],
            "contact_te": r["contact_te"],
            "truth_offender_sim": r["offender_sim"],
            "duplicate_of": r["duplicate_of"],
            "car_behind": r["offender_sim"] if r["contact_te"] is not None else None,
            "accused": None,
        }
        for r in rows
    ]


@pytest.fixture
def data(tmp_path: Path) -> Path:
    d = tmp_path / "racing"
    d.mkdir()
    sessions = {
        H1: {"session": "HEAT 1", "track_short": "Alpha", "incident_limit": 20, "clause": "9.2.1"},
        FE: {"session": "FEATURE", "track_short": "Alpha", "incident_limit": 20, "clause": "9.2.1"},
        RA: {"session": "RACE", "track_short": "Beta", "incident_limit": 25, "clause": "9.2.2"},
    }
    (d / "league.json").write_text(json.dumps({"sessions": sessions}), encoding="utf-8")
    rows = _truth_rows()
    (d / "truth.json").write_text(json.dumps({"decisions": rows}), encoding="utf-8")
    confirmed = {
        "n": 8,
        "car_behind_score": 7,
        "accused_score": 2,
        "better": "car_behind",
        "rows": _const_rows(rows),
    }
    draft = {"constants": {"confirmed": confirmed}}
    (d / "truth.draft.json").write_text(json.dumps(draft), encoding="utf-8")
    catalogue = {
        "decisions": [
            {"id": did, "incident_checks": [{"session": s, "incidents": t} for s, t in checks]}
            for did, checks in CHECKS.items()
        ]
    }
    (d / "catalogue.json").write_text(json.dumps(catalogue), encoding="utf-8")
    inputs = {"catalogue": (d / "catalogue.json").as_posix()}
    (d / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")
    return d


def limit_lines(
    breaches: list[tuple[str, str, int]] = BREACHES, refuse: tuple[str, ...] = ()
) -> list[dict[str, Any]]:
    out = []
    for s, car, total in breaches:
        out.append(
            {
                "id": f"{s}/{car}",
                "kind": "incident_limit",
                "verdict": "breach",
                "offender": car,
                "candidates": [car],
                "window": {"session": s},
                "model_read": None,
                "evidence": f"Car {car} ended the session on {total} incident points, over it.",
            }
        )
    for s in refuse:
        out.append(
            {
                "id": s,
                "kind": "incident_limit",
                "verdict": "unable_to_rule",
                "offender": None,
                "candidates": [],
                "window": {"session": s},
                "model_read": None,
                "evidence": "The incident counter is not shown for every car.",
            }
        )
    return out


def contact_line(
    did: str,
    *,
    te: list[float] | None = None,
    cands: list[str] | None = None,
    read: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s, off, vic, tte, _ = TRUTH[did]
    if te is None:
        centre = tte if tte is not None else 100
        te = [centre - 3, centre + 2]
    if cands is None:
        cands = [p for p in (off, vic) if p]
    return {
        "id": did,
        "kind": "contact",
        "verdict": "steward_review",
        "window": {"session": s, "te": te},
        "candidates": cands,
        "model_read": read,
        "evidence": f"{NAME} was reported; the window holds the reported second.",
    }


def refused_line(did: str) -> dict[str, Any]:
    return {
        "id": did,
        "kind": "contact",
        "verdict": "unable_to_rule",
        "window": {"session": None},
        "candidates": [],
        "model_read": None,
        "evidence": "No feed event holds a protest car on the stated lap.",
    }


def all_contact(**over: dict[str, Any]) -> list[dict[str, Any]]:
    """Every feed protest held with its parties, the no-feed nine refused; `over` replaces lines."""
    lines = {did: contact_line(did) for did in TRUTH}
    lines.update({did: refused_line(did) for did in NOFEED})
    lines.update(over)
    return [v for v in lines.values() if v]


def write(path: Path, lines: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")
    return path


def run(data: Path, lines: list[dict[str, Any]]) -> dict[str, Any]:
    return rs.score([write(data / "preds.jsonl", lines)], data)


# ---------------------------------------------------------------- mark 1


def test_mark1_seven_of_seven_and_the_unruled(data: Path) -> None:
    m = run(data, limit_lines())["mark_1"]
    assert (m["numerator"], m["denominator"], m["pass"]) == (7, 7, True)
    unruled = [
        (b["track"], b["session"], b["car"], b["total"], b["limit"], b["clause"])
        for b in m["no_ruling_on_record"]
    ]
    # Sorted by race day, heat before feature, then car number.
    assert unruled == [
        ("Alpha", "FEATURE", "123", 27, 20, "9.2.1"),
        ("Beta", "RACE", "70", 29, 25, "9.2.2"),
    ]
    assert {b["status"] for b in m["breaches"]} == {"ruled", "no_ruling_on_record"}
    assert sum(b["status"] == "ruled" for b in m["breaches"]) == 7


def test_mark1_six_of_seven_fails(data: Path) -> None:
    # Decision 20's car (HEAT 1, 31) is not over the limit any more: 20 is not found.
    m = run(data, limit_lines([b for b in BREACHES if b != (H1, "5", 31)]))["mark_1"]
    assert (m["numerator"], m["pass"]) == (6, False)
    assert [r["id"] for r in m["rows"] if not r["found"]] == ["20"]
    # A two-part decision needs both parts: losing (FEATURE, 22) drops 26 and 28.
    m = run(data, limit_lines([b for b in BREACHES if b != (FE, "5", 22)]))["mark_1"]
    assert [r["id"] for r in m["rows"] if not r["found"]] == ["26", "28"]


def test_mark1_refused_session_listed(data: Path) -> None:
    lines = limit_lines([b for b in BREACHES if b[0] != H1], refuse=(H1,))
    m = run(data, lines)["mark_1"]
    assert m["refused_sessions"] == ["Alpha HEAT 1"]
    assert m["pass"] is False


def test_mark1_absent_without_limit_lines(data: Path) -> None:
    m = run(data, all_contact())["mark_1"]
    assert m["pass"] is None and m["status"] == "no incident_limit lines"


# ---------------------------------------------------------------- mark 2


def test_mark2_five_of_seven_passes_four_fails(data: Path) -> None:
    far = [1.0, 2.0]
    five = all_contact(**{"1": contact_line("1", te=far), "11": contact_line("11", te=far)})
    m = run(data, five)["mark_2"]
    assert (m["numerator"], m["denominator"], m["pass"]) == (5, 7, True)
    four = all_contact(
        **{
            "1": contact_line("1", te=far),
            "11": contact_line("11", te=far),
            "13": refused_line("13"),
        }
    )
    m = run(data, four)["mark_2"]
    assert (m["numerator"], m["pass"]) == (4, False)
    assert {r["id"]: r["outcome"] for r in m["rows"]}["13"] == "refused"


@pytest.mark.parametrize(
    ("window", "held"),
    [
        ([535.0, 540.0], True),
        ([536.0, 540.0], False),
        ([520.0, 531.0], True),
        ([520.0, 530.0], False),
        ([533.0, 533.0], True),
    ],
)
def test_mark2_two_seconds_inclusive(data: Path, window: list[float], held: bool) -> None:
    m = run(data, all_contact(**{"15": contact_line("15", te=window)}))["mark_2"]
    assert {r["id"]: r["held"] for r in m["rows"]}["15"] is held


def test_mark2_absent_line_is_a_miss_and_unscored_reported(data: Path) -> None:
    lines = [ln for ln in all_contact() if ln["id"] != "46"]
    m = run(data, lines)["mark_2"]
    assert {r["id"]: r["outcome"] for r in m["rows"]}["46"] == "absent"
    assert m["numerator"] == 6
    assert [r["id"] for r in m["unscored"]] == ["14", "18", "23"]
    assert {r["id"]: r["held"] for r in m["unscored"]}["18"] is None


def test_mark2_nofeed_refusals_counted(data: Path) -> None:
    m = run(data, all_contact())["mark_2"]
    assert (m["nofeed"]["count"], m["nofeed"]["present"], m["nofeed"]["refused"]) == (9, 9, 9)
    lines = all_contact(**{"48": contact_line("1") | {"id": "48"}})
    assert run(data, lines)["mark_2"]["nofeed"]["refused"] == 8


# ---------------------------------------------------------------- mark 3


def test_mark3_seven_of_ten_passes_six_fails(data: Path) -> None:
    wrong = {d: contact_line(d, cands=["99"]) for d in ("1", "11", "13")}
    m = run(data, all_contact(**wrong))["mark_3"]
    assert (m["numerator"], m["denominator"], m["parties_pass"], m["pass"]) == (7, 10, True, True)
    wrong["16"] = contact_line("16", cands=["68"])  # the victim is left out
    m = run(data, all_contact(**wrong))["mark_3"]
    assert (m["numerator"], m["parties_pass"], m["pass"]) == (6, False, False)


def test_mark3_missing_victim_needs_only_the_offender(data: Path) -> None:
    m = run(data, all_contact(**{"18": contact_line("18", cands=["5"])}))["mark_3"]
    row = {r["id"]: r for r in m["rows"]}["18"]
    assert row["parties"] == ["5"] and row["inside"] is True


def test_mark3_refused_is_size_zero_and_a_miss(data: Path) -> None:
    m = run(data, all_contact(**{"24": refused_line("24")}))["mark_3"]
    row = {r["id"]: r for r in m["rows"]}["24"]
    assert (row["size"], row["inside"], row["outcome"]) == (0, False, "refused")
    assert m["numerator"] == 9


def test_mark3_median_four_passes_five_fails(data: Path) -> None:
    def sized(n: int) -> dict[str, Any]:
        out = {}
        for did, (_, off, vic, _, _) in TRUTH.items():
            base = [p for p in (off, vic) if p]
            out[did] = contact_line(did, cands=base + [str(900 + i) for i in range(n - len(base))])
        return out

    m = run(data, all_contact(**sized(4)))["mark_3"]
    assert (m["median_size"], m["median_pass"], m["pass"]) == (4.0, True, True)
    m = run(data, all_contact(**sized(5)))["mark_3"]
    assert (m["median_size"], m["median_pass"], m["pass"]) == (5.0, False, False)
    # Even count: the median of 10 is the mean of the middle two.
    mixed = sized(4)
    for did in ("1", "11", "13", "14", "15"):
        mixed[did] = contact_line(did, cands=[p for p in TRUTH[did][1:3] if p] + ["901"] * 3)
    m = run(data, all_contact(**mixed))["mark_3"]
    assert m["median_size"] == 4.5 and m["median_pass"] is False


def test_mark3_duplicates_view_and_both_denominators(data: Path) -> None:
    m = run(data, all_contact(**{"1": contact_line("1", cands=["99"])}))["mark_3"]
    v = m["view_deduplicated"]
    assert (v["numerator"], v["denominator"], v["dropped"]) == (7, 8, ["14", "23"])
    assert (m["without_decision_1"]["numerator"], m["without_decision_1"]["denominator"]) == (9, 9)
    assert (m["rule_b"]["right"], m["rule_b"]["n"]) == (2, 9)


# ---------------------------------------------------------------- marks 4 and 5


def _read(off: str | None, agreed: bool = True, verdict: str = "penalty") -> dict[str, Any]:
    return {
        "model": "m",
        "runs": 3,
        "agreed": agreed,
        "verdict": verdict,
        "offender": off,
        "reason": "x" * 40,
    }


def test_marks45_not_run_yet(data: Path) -> None:
    s = run(data, all_contact())
    assert s["mark_4"]["status"] == s["mark_5"]["status"] == "not run yet"
    assert "not run yet" in rs.render(s)


def test_mark4_eight_of_eight_passes_seven_fails(data: Path) -> None:
    reads = {d: contact_line(d, read=_read(TRUTH[d][1])) for d in TRUTH}
    m4 = run(data, all_contact(**reads))["mark_4"]
    assert (m4["numerator"], m4["denominator"], m4["pass_at"], m4["pass"]) == (8, 8, 8, True)
    # A read that is right but not agreed on all three runs does not count.
    reads["46"] = contact_line("46", read=_read("01", agreed=False))
    s = run(data, all_contact(**reads))
    assert (s["mark_4"]["numerator"], s["mark_4"]["pass"]) == (7, False)
    assert s["mark_5"]["numerator"] == 7 and s["mark_5"]["status"] == "reported, no mark"


def test_mark4_duplicates_out_of_n(data: Path) -> None:
    reads = {d: contact_line(d, read=_read("0")) for d in ("14", "23")}
    m4 = run(data, all_contact(**reads))["mark_4"]
    assert [r["id"] for r in m4["rows"]] == ["1", "11", "13", "15", "16", "18", "24", "46"]
    assert m4["numerator"] == 0


def test_mark4_beats_a_lower_constant(data: Path) -> None:
    draft = json.loads((data / "truth.draft.json").read_text(encoding="utf-8"))
    draft["constants"]["confirmed"]["car_behind_score"] = 5
    (data / "truth.draft.json").write_text(json.dumps(draft), encoding="utf-8")
    reads = {d: contact_line(d, read=_read(TRUTH[d][1])) for d in ("1", "11", "13", "15", "16")}
    m4 = run(data, all_contact(**reads))["mark_4"]
    assert (m4["pass_at"], m4["numerator"], m4["pass"]) == (6, 5, False)
    reads["24"] = contact_line("24", read=_read("12"))
    assert run(data, all_contact(**reads))["mark_4"]["pass"] is True


# ---------------------------------------------------------------- constants


def test_constants_stored_when_they_match(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rs, "recompute", lambda _d: pytest.fail("should not recompute"))
    c = run(data, all_contact())["constants"]
    assert c["source"].startswith("stored")
    assert (c["n"], c["car_behind"], c["accused"], c["better_score"]) == (8, 7, 2, 7)


def test_constants_recomputed_when_stale(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    truth = json.loads((data / "truth.json").read_text(encoding="utf-8"))
    truth["decisions"][0]["contact_te"] = 176
    (data / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
    called = []

    def fake(d: Path) -> dict[str, Any]:
        called.append(d)
        return {"n": 8, "car_behind_score": 6, "accused_score": 2, "better": "car_behind"}

    monkeypatch.setattr(rs, "recompute", fake)
    c = run(data, all_contact())["constants"]
    assert called == [data] and c["source"].startswith("recomputed") and c["car_behind"] == 6


# ---------------------------------------------------------------- the file and the table


def test_duplicate_ruling_id_refused(data: Path) -> None:
    a = write(data / "a.jsonl", [contact_line("1")])
    b = write(data / "b.jsonl", [contact_line("1")])
    with pytest.raises(rs.ScoreError, match="repeats ruling id 1"):
        rs.score([a, b], data)


def test_deterministic_and_nameless(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lim = write(data / "limits.jsonl", limit_lines())
    loc = write(data / "locate.jsonl", all_contact())
    args = [str(lim), str(loc), "--data", str(data)]
    outs, files = [], []
    for _ in range(2):
        assert rs.main(args) == 0
        outs.append(capsys.readouterr().out)
        files.append((data / "score.json").read_bytes())
    assert outs[0] == outs[1] and files[0] == files[1]
    assert not (data / "score.json.tmp").exists()
    text = files[0].decode("utf-8")
    assert json.loads(text) == json.loads(json.dumps(json.loads(text), sort_keys=True))
    for blob in (outs[0], text):
        assert "Driver" not in blob and "lap 3" not in blob
        assert "100/" not in blob and "200/" not in blob  # no subsession ids
    assert "over the limit, no ruling on record" in outs[0]
    assert "missed breach" not in outs[0] and "breach the stewards missed" not in outs[0]
    for word in ("mark 1", "mark 2", "mark 3", "mark 4", "mark 5", "-> pass"):
        assert word in outs[0]


def test_bad_input_exits_one(data: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert rs.main([str(data / "nope.jsonl"), "--data", str(data)]) == 1
    assert "nope.jsonl" in capsys.readouterr().err


def test_mark2_one_second_outside_held_by_mark_missed_by_view(data: Path) -> None:
    # Truth 533; the window ends at 532, so the second is 1 s outside it.
    s = run(data, all_contact(**{"15": contact_line("15", te=[528.0, 532.0])}))
    m = s["mark_2"]
    assert {r["id"]: r["held"] for r in m["rows"]}["15"] is True
    v = m["view_no_tolerance"]
    assert {r["id"]: r["held"] for r in v["rows"]}["15"] is False
    assert (m["numerator"], v["numerator"], v["denominator"]) == (7, 6, 7)
    table = rs.render(s)
    assert f"{rs.VIEW_NO_TOL}: 6 of 7" in table and "15 missed" in table


# ---------------------------------------------------------------- review fixes


def test_refused_line_with_te_is_a_miss_for_marks_2_and_3(data: Path) -> None:
    refused = contact_line("15") | {"verdict": "unable_to_rule"}  # te still holds 533
    s = run(data, all_contact(**{"15": refused}))
    r2 = {r["id"]: r for r in s["mark_2"]["rows"]}["15"]
    assert (r2["held"], r2["outcome"], r2["width_s"]) == (False, "refused", None)
    assert s["mark_2"]["numerator"] == 6
    assert {r["id"]: r["held"] for r in s["mark_2"]["view_no_tolerance"]["rows"]}["15"] is False
    r3 = {r["id"]: r for r in s["mark_3"]["rows"]}["15"]
    assert (r3["inside"], r3["size"]) == (False, 0)
    assert s["mark_3"]["numerator"] == 9


def test_mark4_read_on_a_refused_line_not_counted(data: Path) -> None:
    reads = {d: contact_line(d, read=_read(TRUTH[d][1])) for d in TRUTH}
    reads["46"] = reads["46"] | {"verdict": "unable_to_rule"}
    s = run(data, all_contact(**reads))
    row = {r["id"]: r for r in s["mark_4"]["rows"]}["46"]
    assert row["read"] == "not counted: line not located" and row["offender_right"] is False
    assert (s["mark_4"]["numerator"], s["mark_4"]["pass"]) == (7, False)
    assert s["mark_5"]["numerator"] == 7


def test_mark4_offender_outside_candidates_not_counted(data: Path) -> None:
    reads = {d: contact_line(d, read=_read(TRUTH[d][1])) for d in TRUTH}
    reads["46"] = contact_line("46", cands=["34"], read=_read("01"))
    s = run(data, all_contact(**reads))
    row = {r["id"]: r for r in s["mark_4"]["rows"]}["46"]
    assert row["read"] == "not counted: offender outside candidates"
    assert (s["mark_4"]["numerator"], s["mark_4"]["pass"]) == (7, False)
    assert s["mark_5"]["numerator"] == 7


def test_mark3_both_medians_must_pass(data: Path) -> None:
    # Three refused (size 0); seven located with sizes 2, 2, 5, 5, 5, 5, 5, every party inside.
    # Over all 10 the median is (2 + 5) / 2 = 3.5, a pass; over the 7 located it is 5, a fail.
    def sized(did: str, n: int) -> dict[str, Any]:
        base = [p for p in TRUTH[did][1:3] if p]
        return contact_line(did, cands=base + [str(900 + i) for i in range(n - len(base))])

    over: dict[str, Any] = {d: refused_line(d) for d in ("1", "11", "13")}
    over |= {d: sized(d, 2) for d in ("14", "15")}
    over |= {d: sized(d, 5) for d in ("16", "18", "23", "24", "46")}
    s = run(data, all_contact(**over))
    m = s["mark_3"]
    assert (m["numerator"], m["parties_pass"]) == (7, True)
    assert (m["median_size"], m["median_pass"]) == (3.5, True)
    assert (m["median_size_located"], m["located"], m["median_located_pass"]) == (5.0, 7, False)
    assert m["pass"] is False
    assert "over the 7 located: 5 -> fail" in rs.render(s)
    # Located sizes all 4: both medians pass and the mark passes.
    over |= {d: sized(d, 4) for d in ("16", "18", "23", "24", "46")}
    m = run(data, all_contact(**over))["mark_3"]
    assert (m["median_size_located"], m["median_located_pass"], m["pass"]) == (4.0, True, True)


def test_mark2_window_widths(data: Path) -> None:
    lines = all_contact(**{"1": contact_line("1", te=[170.0, 180.0]), "11": refused_line("11")})
    m = run(data, lines)["mark_2"]
    widths = {r["id"]: r["width_s"] for r in m["rows"]}
    assert widths["1"] == 10.0 and widths["11"] is None and widths["13"] == 5.0
    assert m["window_width"] == {"median_s": 5.0, "over": 6, "of": 7}


def test_mark1_two_breach_lines_for_one_car_refused(data: Path) -> None:
    with pytest.raises(rs.ScoreError, match="second breach line for car 18"):
        run(data, limit_lines() + [limit_lines([(H1, "18", 22)])[0] | {"id": "dup"}])


@pytest.mark.parametrize(
    "draft",
    [
        [1, 2],
        {"constants": [1]},
        {"constants": {"confirmed": "x"}},
        {"constants": {"confirmed": {"rows": [1], "n": 8}}},
    ],
)
def test_bad_constants_block_raises_score_error(data: Path, draft: Any) -> None:
    (data / "truth.draft.json").write_text(json.dumps(draft), encoding="utf-8")
    with pytest.raises(rs.ScoreError, match="truth.draft.json"):
        run(data, all_contact())
