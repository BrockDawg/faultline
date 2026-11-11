"""scripts/racing_card.py: deterministic pages, the lint refusal, the read wording, the limit page.

Everything here is made up: sessions 100 and 200 on tracks "Alpha" and "Beta", invented car
numbers, invented names ("Test Driver A") and a league called "Test League", and tiny frame
files with a JPEG's opening and closing markers. Only the last test reads the private corpus.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_ROOT

SCRIPT = REPO_ROOT / "scripts" / "racing_card.py"
sys.path.insert(0, str(SCRIPT.parent))
import racing_card as rc  # noqa: E402

NAME = "Test Driver A"
NAMES = [NAME] + [f"Test Driver {c}" for c in "BCDEFGHIJKL"]
LEAGUE = "Test League"
H1, RA = "100/HEAT 1", "200/RACE"
LOG = REPO_ROOT / "experiments" / "2026-10-29-racing-pipeline" / "LOG.md"
# id: (session, offender, victim, contact_te, duplicate_of)
TRUTH = {
    "1": (H1, "7", "8", 175, None),
    "11": (RA, "41", "22", 3787, None),
    "13": (RA, "44", "26", 1387, None),
    "14": (RA, "70", "32", 533, "15"),
    "15": (RA, "70", "32", 533, None),
    "16": (H1, "68", "18", 299, None),
    "18": (H1, "5", "9", None, None),
    "23": (RA, "12", "18", 2471, "24"),
    "24": (RA, "12", "18", 2471, None),
    "46": (H1, "01", "34", 162, None),
}


def _jpeg(seed: int) -> bytes:
    return b"\xff\xd8\xff\xe0" + bytes([seed % 256]) * 16 + b"\xff\xd9"


def _read(model: str, agreed: bool, offender: str | None, verdict: str | None) -> dict:
    return {
        "agreed": agreed,
        "lint_hits": 0,
        "model": model,
        "offender": offender,
        "parse_failures": 0,
        "reason": None,
        "runs": 3,
        "source": "model",
        "verdict": verdict,
    }


def _line(did: str, session: str, te0: int, s0: float, read: dict | None, facts: list[str]):
    frames = [{"sha256": "", "stream_s": s0 - 1 + 0.5 * k} for k in range(17)]
    return {
        "id": did,
        "kind": "contact",
        "candidates": ["9", "5"] if did == "18" else ["8", "7", "12"],
        "clause": None,
        "evidence": f"{NAME} wrote a protest.",
        "facts": facts,
        "frames": frames,
        "missing_fact": None,
        "model_read": read,
        "offender": None,
        "record": "0" * 64,
        "rule": "S21",
        "verdict": "steward_review",
        "victim": None,
        "window": {
            "lap": 3,
            "offset_error_s": 2.0,
            "session": session,
            "stream_s": [s0, s0 + 5],
            "te": [te0, te0 + 5],
        },
    }


NV, PEN5 = ("not_visible", None), ("penalty", "5")
LABELS = [f"F{k}" for k in range(1, 9)]


def _reply(verdict: str, offender: str | None) -> str:
    reason = "The frames show spray around the cars and the rule asks for a clear view."
    body = {"offender": offender, "verdict": verdict, "reason": reason, "frames_used": ["F1"]}
    return json.dumps(body)


def _bundle(
    data: Path, arm: int, line: dict[str, Any], centre: tuple[int, float] | None, runs: list
) -> None:
    """The line's record bundle, and its run replies in the ledger (a model call when `runs`)."""
    rec = hashlib.sha256(f"{arm}-{line['id']}".encode()).hexdigest()
    line["record"] = rec
    inputs: dict[str, Any] = {"stage": "rule"}
    detail: dict[str, Any] = {}
    if centre is not None:
        inputs["moment"] = {"te": centre[0], "source": "a made-up check"}
        detail["frames"] = {"centre_te": centre[0], "centre_s": centre[1]}
    if runs:
        keys = []
        for k, (verdict, offender) in enumerate(runs):
            key = hashlib.sha256(f"{rec}-{k}".encode()).hexdigest()
            keys.append(key)
            ledger = data / "ledger"
            ledger.mkdir(exist_ok=True)
            entry = {"reply": _reply(verdict, offender), "model": "m"}
            (ledger / f"{key}.json").write_text(json.dumps(entry), encoding="utf-8")
        inputs["ledger_keys"] = keys
        inputs["model_call"] = {
            "candidates": line["candidates"],
            "frame_labels": LABELS,
            # the run sends 8 frames: every other one, from the second frame
            "frame_sha256": [f["sha256"] for f in line["frames"][1:17:2]],
            "images": 8,
        }
    folder = data / f"preds-arm{arm}.jsonl.record"
    folder.mkdir(exist_ok=True)
    (folder / f"{rec}.json").write_text(
        json.dumps({"inputs": inputs, "detail": detail}), encoding="utf-8"
    )


def make_corpus(
    tmp: Path,
    *,
    fact: str = "Car 7 closed on car 8 at second 175.",
    moment_on_1: bool = True,
    arm1_runs_18: tuple = (NV, NV, PEN5),
) -> Path:
    data = tmp / "data"
    data.mkdir()
    sessions = {
        H1: {"track": "Alpha Raceway", "track_short": "Alpha", "session": "HEAT 1"},
        RA: {"track": "Beta Circuit", "track_short": "Beta", "session": "RACE"},
    }
    for key, s in sessions.items():
        s.update(incident_limit=20 if key == H1 else 25, clause="9.2.1" if key == H1 else "9.2.2")
    league = {"pack": {"rule_id": "S21"}, "number_map": {}, "sessions": sessions}
    (data / "league.json").write_text(json.dumps(league), encoding="utf-8")
    truth = {
        "decisions": [
            {
                "id": did,
                "session": s,
                "offender_sim": o,
                "victim_sim": v,
                "contact_te": te,
                "duplicate_of": dup,
                "verdict": "penalty",
                "basis": f"confirmed by {NAME}",
                "confirmed_by": NAME,
            }
            for did, (s, o, v, te, dup) in TRUTH.items()
        ],
        "notes": {"18": f"{NAME} filed it"},
    }
    (data / "truth.json").write_text(json.dumps(truth), encoding="utf-8")
    pack = tmp / "test-league-pack"
    pack.mkdir()
    (pack / "pack.json").write_text(json.dumps({"name": LEAGUE}), encoding="utf-8")
    catalogue = tmp / "catalogue.json"
    catalogue.write_text(json.dumps({"decisions": []}), encoding="utf-8")
    inputs = {"catalogue": str(catalogue), "pack_dir": str(pack)}
    (data / "inputs.json").write_text(json.dumps(inputs), encoding="utf-8")

    arms = {
        2: [
            _line("1", H1, 172, 1567.5, _read("muse-spark-1.3", True, "7", "penalty"), [fact]),
            _line("18", H1, 319, 2382.0, _read("muse-spark-1.3", True, None, "not_visible"), []),
        ],
        1: [
            _line("1", H1, 172, 1567.5, None, [fact]),
            _line("18", H1, 319, 2382.0, _read("spark-open", False, None, None), []),
        ],
    }
    seed = 0
    for arm, lines in arms.items():
        fdir = data / f"preds-arm{arm}.jsonl.frames"
        fdir.mkdir()
        for line in lines:
            for f in line["frames"]:
                raw = _jpeg(seed)
                seed += 1
                f["sha256"] = hashlib.sha256(raw).hexdigest()
                (fdir / f"{f['sha256']}.jpg").write_bytes(raw)
        one, eighteen = lines
        _bundle(data, arm, one, (175, 1570.5) if moment_on_1 else None, [("penalty", "7")] * 3)
        runs_18 = [NV, NV, NV] if arm == 2 else list(arm1_runs_18)
        _bundle(data, arm, eighteen, (322, 2385.0), runs_18)
        text = "".join(json.dumps(r) + "\n" for r in lines)
        (data / f"preds-arm{arm}.jsonl").write_text(text, encoding="utf-8")

    limits = [
        ("L1", RA, "9", 27),
        ("L2", RA, "418", 29),
        ("L3", H1, "91", 22),
    ]
    rows = [
        {
            "id": rid,
            "kind": "incident_limit",
            "window": {"session": session},
            "verdict": "breach",
            "offender": car,
            "evidence": f"Car {car} finished on {total} incident points.",
        }
        for rid, session, car, total in limits
    ]
    (data / "limits-a.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )
    return data


@pytest.fixture
def fake_names(monkeypatch: pytest.MonkeyPatch) -> None:
    """The feed names are faked; the league's name is read from the fixture's real pack.json."""
    monkeypatch.setattr(rc, "feed_names", lambda data: NAMES)


def _run(data: Path, out: Path) -> int:
    return rc.main(["--data", str(data), "--out", str(out)])


def _files(out: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(out.iterdir())}


def test_two_runs_are_byte_identical(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path)
    out = tmp_path / "cards"
    assert _run(data, out) == 0
    first = _files(out)
    assert _run(data, out) == 0
    assert _files(out) == first
    assert sorted(first) == [
        "decision-1.html",
        "decision-18.html",
        "honesty-18.html",
        "index.html",
        "over-limit-alpha-heat-1.html",
        "over-limit-beta-race.html",
    ]
    for raw in first.values():
        assert b"\r" not in raw
        raw.decode("utf-8")
    assert not list(out.glob("*.tmp"))


def test_a_planted_name_refuses_and_writes_nothing(
    tmp_path: Path, fake_names: None, capsys: pytest.CaptureFixture[str]
) -> None:
    data = make_corpus(tmp_path, fact=f"Car 7 ({NAME}) closed on car 8.")
    out = tmp_path / "cards"
    assert _run(data, out) == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "decision-1.html" in err and "refused" in err
    assert NAME not in err and "Driver" not in err


def test_the_league_name_run_together_refuses(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path, fact="Car 7 raced in the TestLeague cup.")
    assert _run(data, tmp_path / "cards") == 1


def test_no_name_or_truth_prose_reaches_any_page(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path)
    out = tmp_path / "cards"
    assert _run(data, out) == 0
    for name, raw in _files(out).items():
        text = raw.decode("utf-8")
        assert "Driver" not in text, name
        assert "confirmed by" not in text, name
        assert "wrote a protest" not in text, name


def test_no_agreed_read_shows(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path)
    out = tmp_path / "cards"
    assert _run(data, out) == 0
    one = rc.visible_text((out / "decision-1.html").read_text(encoding="utf-8"))
    eighteen = rc.visible_text((out / "decision-18.html").read_text(encoding="utf-8"))
    # Arm 1 has no model_read at all on 1, and a read that did not agree on 18.
    assert "The model's read, Arm 1 (model)\nno agreed read" in one
    assert "Arm 1 (spark-open)\nno agreed read (runs disagree)" in eighteen
    # Arm 2 agreed: a car on 1, no car on 18.
    assert "Arm 2 (Spark 1.3)\npenalty, agreed over 3 runs\n7" in one
    assert "Arm 2 (Spark 1.3)\nnot visible, agreed over 3 runs\nno car named" in eighteen
    assert "The steward's final\npenalty\n7 (contact with 8)" in one


def test_over_limit_page_title_and_rows(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path)
    out = tmp_path / "cards"
    assert _run(data, out) == 0
    text = (out / "over-limit-beta-race.html").read_text(encoding="utf-8")
    assert "<title>Over the limit, no ruling on record</title>" in text
    assert "<h1>Over the limit, no ruling on record</h1>" in text
    visible = rc.visible_text(text)
    assert "9\n27\n25\n9.2.2\n418\n29\n25\n9.2.2" in visible
    index = rc.visible_text((out / "index.html").read_text(encoding="utf-8"))
    assert "3 cars over the limit with no ruling on record" in index


def test_frames_are_embedded_and_labelled(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path)
    out = tmp_path / "cards"
    assert _run(data, out) == 0
    text = (out / "decision-1.html").read_text(encoding="utf-8")
    uris = re.findall(r"data:image/jpeg;base64,([A-Za-z0-9+/=]+)", text)
    assert len(uris) == 17
    line = json.loads((data / "preds-arm2.jsonl").read_text(encoding="utf-8").splitlines()[0])
    want = [(data / "preds-arm2.jsonl.frames" / f"{f['sha256']}.jpg") for f in line["frames"]]
    assert [base64.b64decode(u) for u in uris] == [p.read_bytes() for p in want]
    visible = rc.visible_text(text)
    assert "stream 1566.5 s" in visible and "stream 1570.5 s\nthe moment" in visible
    assert visible.count("sent to the model") == 8 + 1  # 8 tags and the strip's note


def _captions(text: str) -> dict[str, str]:
    return dict(re.findall(r"<b>stream (\S+) s</b>(.*?)</figcaption>", text))


def test_sent_tags_follow_the_recorded_call(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path)
    out = tmp_path / "cards"
    assert _run(data, out) == 0
    caps = _captions((out / "decision-1.html").read_text(encoding="utf-8"))
    sent = sorted(s for s, c in caps.items() if "sent to the model" in c)
    # The record sent every other frame from the second: whole seconds 1567 to 1574, which
    # is not what the default picker would choose around the moment (1566.5, 1567.5, ...).
    assert sent == [f"{1567 + k}.0" for k in range(8)]
    assert "steward's moment" in caps["1570.5"]


def test_a_line_with_no_moment_marks_no_centre(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path, moment_on_1=False)
    out = tmp_path / "cards"
    assert _run(data, out) == 0
    text = (out / "decision-1.html").read_text(encoding="utf-8")
    visible = rc.visible_text(text)
    assert "steward's moment</span>" not in text and "the moment" not in visible
    assert "Steward's moment\nnone on this line (the locator's window)" in visible
    assert "no steward's moment on this line" in visible
    # The sent frames are still the recorded ones.
    caps = _captions(text)
    assert sum("sent to the model" in c for c in caps.values()) == 8


@pytest.mark.parametrize(
    ("arm1_runs", "claim"),
    [
        ((NV, NV, NV), "Arm 1's three runs disagreed"),
        ((NV, NV, ("penalty", "9")), "Arm 1's three runs disagreed"),
    ],
)
def test_honesty_card_refuses_when_the_runs_do_not_hold_the_claim(
    tmp_path: Path,
    fake_names: None,
    capsys: pytest.CaptureFixture[str],
    arm1_runs: tuple,
    claim: str,
) -> None:
    data = make_corpus(tmp_path, arm1_runs_18=arm1_runs)
    out = tmp_path / "cards"
    assert _run(data, out) == 1
    assert not out.exists()
    err = capsys.readouterr().err
    assert "honesty-18.html: refused" in err and claim in err


def test_honesty_card_refuses_when_arm2_did_not_agree(
    tmp_path: Path, fake_names: None, capsys: pytest.CaptureFixture[str]
) -> None:
    data = make_corpus(tmp_path)
    path = data / "preds-arm2.jsonl"
    rows = [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()]
    rows[1]["model_read"]["agreed"] = False
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    assert _run(data, tmp_path / "cards") == 1
    assert "Arm 2 agreed on all three runs" in capsys.readouterr().err


def test_stale_pages_are_cleared_only_at_the_top_level(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path)
    out = tmp_path / "cards"
    (out / "sub").mkdir(parents=True)
    for name in ("decision-99.html", "index.html.tmp", "notes.txt", "sub/deep.html"):
        (out / name).write_text("old", encoding="utf-8")
    assert _run(data, out) == 0
    assert not (out / "decision-99.html").exists()
    assert not (out / "index.html.tmp").exists()
    assert (out / "notes.txt").read_text(encoding="utf-8") == "old"
    assert (out / "sub" / "deep.html").read_text(encoding="utf-8") == "old"
    assert (out / "decision-1.html").is_file()


def test_a_refused_run_clears_nothing(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path, fact=f"Car 7 ({NAME}) closed on car 8.")
    out = tmp_path / "cards"
    out.mkdir()
    (out / "decision-99.html").write_text("old", encoding="utf-8")
    assert _run(data, out) == 1
    assert (out / "decision-99.html").read_text(encoding="utf-8") == "old"


@pytest.mark.parametrize("body", ["{not json", "[1, 2]"])
def test_a_bad_pack_json_exits_one(
    tmp_path: Path, fake_names: None, capsys: pytest.CaptureFixture[str], body: str
) -> None:
    data = make_corpus(tmp_path)
    (tmp_path / "test-league-pack" / "pack.json").write_text(body, encoding="utf-8")
    assert _run(data, tmp_path / "cards") == 1
    assert "pack.json" in capsys.readouterr().err


def test_a_frame_that_does_not_hash_to_its_name_refuses(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path)
    frame = sorted((data / "preds-arm2.jsonl.frames").iterdir())[0]
    frame.write_bytes(_jpeg(250) + b"x")
    for p in (data / "preds-arm1.jsonl.frames").glob(frame.name):
        p.unlink()
    assert _run(data, tmp_path / "cards") == 1


def test_absent_corpus_exits_non_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _run(tmp_path / "nothing", tmp_path / "cards") == 1
    assert "private corpus absent" in capsys.readouterr().err
    assert not (tmp_path / "cards").exists()


def test_frame_look_and_honesty_wording_are_the_logs_own() -> None:
    log = LOG.read_text(encoding="utf-8")
    for did, look in rc.FRAME_LOOK.items():
        assert f"| {did} | {look} |" in log
    assert rc.FRAME_LOOK_NOTE in log
    assert rc.NO_RULING_LEAD in log
    honesty = log.split("### The honesty card, decision 18", 1)[1].split("\n### ", 1)[0]
    for sentence in rc.HONESTY_LINES:
        assert f"- {sentence}\n" in honesty


def test_honesty_card_shows_the_verdict_token_as_plain_words(
    tmp_path: Path, fake_names: None
) -> None:
    data = make_corpus(tmp_path)
    out = tmp_path / "cards"
    assert _run(data, out) == 0
    text = (out / "honesty-18.html").read_text(encoding="utf-8")
    assert "<code>" not in text and "not_visible" not in text
    visible = rc.visible_text(text)
    # The one display change from the LOG: the backticked `not_visible` reads as "not visible".
    for sentence in rc.HONESTY_LINES:
        assert sentence.replace("`not_visible`", "not visible") in visible


def test_mark4_line_separates_arm_and_numbers(tmp_path: Path, fake_names: None) -> None:
    data = make_corpus(tmp_path)
    for arm in (1, 2):
        m4 = {"status": "scored", "numerator": 4, "denominator": 8, "pass": False, "pass_at": 8}
        (data / f"score-arm{arm}.json").write_text(json.dumps({"mark_4": m4}), encoding="utf-8")
    out = tmp_path / "cards"
    assert _run(data, out) == 0
    visible = rc.visible_text((out / "decision-1.html").read_text(encoding="utf-8"))
    assert (
        "Mark 4, offender named and right: arm 2, 4 of 8; arm 1, 4 of 8;"
        " the mark is 8 of 8 (fail on both)." in visible
    )


@pytest.mark.private
def test_real_corpus_cards(tmp_path: Path) -> None:
    data = REPO_ROOT / "data" / "racing"
    if not (data / "preds-arm2.jsonl").is_file():
        pytest.skip("private corpus absent")
    out = tmp_path / "cards"
    assert rc.main(["--data", str(data), "--out", str(out)]) == 0
    names = sorted(p.name for p in out.iterdir())
    assert sum(n.startswith("decision-") for n in names) == 8
    assert "honesty-18.html" in names and "index.html" in names
    index = rc.visible_text((out / "index.html").read_text(encoding="utf-8"))
    assert "21 cars over the limit with no ruling on record" in index
    first: dict[str, Any] = _files(out)
    assert rc.main(["--data", str(data), "--out", str(out)]) == 0
    assert _files(out) == first
