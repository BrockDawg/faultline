"""Write the racing evidence cards: self-contained HTML pages for the demo. No model call.

Run from the repo root:
    uv run python scripts/racing_card.py [--data data/racing] [--out <data>/cards]
        [--limits <data>/limits-a.jsonl] [--known-names <file>]

Inputs, all read in place from the private folder `<data>`:

- `preds-arm2.jsonl` and `preds-arm1.jsonl`, the judge's contact lines (the plan's "Ruling
  line"), and each one's `.frames/` folder of JPEGs named `<sha256>.jpg`. Every frame a card
  shows is read from arm 2's folder (arm 1's when arm 2's lacks it) and must hash to its name.
- `truth.json`, the table confirmed by hand: each card's "steward's final" is its `verdict`,
  `offender_sim` and `victim_sim`. No other truth field is copied (`basis`, `confirmed_by` and
  `notes` never reach a card).
- `league.json` for each session's track, session name, incident limit and clause.
- The limits output (`--limits`, default `limits-a.jsonl`), joined to the 28 Oct catalogue named
  by `inputs.json` exactly as `scripts/racing_score.py` mark 1 joins it (its own function is
  called), to list each breach with no ruling on record.
- `score-arm2.json` and `score-arm1.json` when present, for the mark 4 line under each read.

Writes into `--out` (default `<data>/cards`, inside the git-ignored private folder):

- `decision-<id>.html`, one per contact line in arm 2: the frame strip (each frame embedded
  as a data URI and labelled with its stream second, the steward's moment and the frames sent
  to the model marked, both as the run recorded them in the line's bundle
  `<preds>.record/<record>.json`: `inputs.moment` with `detail.frames.centre_s`, and
  `inputs.model_call.frame_sha256`; a line with no moment marks no centre), the window and
  lap, the closed candidate set, the facts, the model's read on arm 2 and arm 1 ("no agreed
  read" when a read is absent or not agreed), and the steward's final.
- `over-limit-<track>-<session>.html`, one per session holding a breach with no ruling on
  record, titled "Over the limit, no ruling on record": car, total, limit and clause.
- `honesty-18.html`: decision 18's model reads beside the frame look, in the words of
  `experiments/2026-10-29-racing-pipeline/LOG.md` ("The frame look, per protest" and "The
  honesty card, decision 18"), a backticked verdict token shown as plain words. Before it is
  built, the data must hold what those sentences claim: arm 2 agreed `not_visible` with no car
  on all three runs, arm 1 did not agree with two `not_visible` runs and one naming car 5 for
  a penalty (each run judged again from the ledger, `<data>/ledger`, under the bundle's
  `ledger_keys`), and truth names car 5; otherwise the run is refused, naming the claim.
- `index.html`, linking every page.

Each page is UTF-8 with `\\n` endings, holds no timestamp and loads nothing from outside, so the
same inputs give byte-identical files. Every page is built and checked before any is written.
Then every `*.html` directly in `--out` that this run does not write, and any stale `*.tmp`,
is removed (no subfolder is touched), and each page is written to a temp file then renamed.

Names. Car numbers only. The lint names are the adapter's own list (every driver name in every
session feed of `league.json`, read through the adapter's league reader) plus the lines of
`--known-names`; the league's name (the pack folder's name and its `pack.json` name) is banned
as a phrase and, with spaces removed, as a run. Every page's visible text (text nodes plus
`alt` and `title`) passes `faultline.lint.assert_clean` with the adapter's `ALLOW`.

Refuses (exit 1, nothing written, a message naming the file or page and the reason) when the
private corpus is absent, an input is missing or bad, a frame is missing or does not hash to
its name, or any page's visible text hits the lint. A lint refusal names the page, the hit
kinds and offsets, never the matched text.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import racing_score as score  # noqa: E402

from faultline import lint  # noqa: E402
from faultline import ruling as modelread  # noqa: E402
from faultline.adapters.pitbot import cli as pitbot  # noqa: E402
from faultline.ledger import Ledger, LedgerError  # noqa: E402

ARMS = (2, 1)  # shown in this order: arm 2 is the arm the LOG's rule names first
MODEL_LABELS = {
    "muse-spark-1.3": "Spark 1.3",
    "meta-models/muse-spark-open-1026": "Spark Open",
}
VERDICT_WORDS = {
    "penalty": "penalty",
    "racing_incident": "racing incident",
    "no_action": "no action",
    "not_visible": "not visible",
}
NO_READ = "no agreed read"
NO_RULING_TITLE = "Over the limit, no ruling on record"
HONESTY_ID = "18"
# Verbatim from the LOG, "Over the limit, no ruling on record".
NO_RULING_LEAD = (
    "Under code 9.9 only reported incidents are ruled, and only the stewards can say why no "
    "ruling exists."
)
# Verbatim from the LOG, "The frame look, per protest".
FRAME_LOOK_NOTE = "This is a look, not a score."
FRAME_LOOK = {
    "1": "A line of cars, then a car alongside; no clear contact",
    "11": "Two cars close together through a bend",
    "13": "A pack through the first corner; contact not clear at this camera",
    "15": "A high wide shot of a group through the chicane; the cars are small",
    "16": "The contact: debris and a spun car",
    "18": (
        "Heavy spray, then cars side by side after the pile-up; the contact itself is not "
        "clearly in frame"
    ),
    "24": "A group at the hairpin, with smoke",
    "46": "A pack, then smoke and a car off the track",
}
# Verbatim from the LOG, "The honesty card, decision 18".
HONESTY_LINES = (
    "At decision 18's moment, the frame look found spray and then the cars after the pile-up, "
    "with the contact itself not clearly in frame.",
    "Arm 2 agreed on all three runs that the contact is not visible, and named no car.",
    "Arm 1's three runs disagreed: two said `not_visible` and one named car 5 for a penalty.",
    "That one run read something the frames do not show, and the agreement gate kept it out of "
    "the read.",
    "The steward's ruling names car 5.",
    "No agreed read claimed to see what the frames do not show.",
)
READ_NOTE = "Each model's read is a read beside the evidence, never a ruling."


class CardError(ValueError):
    """A card could not be built or written; the message names the file or page and the reason."""


# ---------------------------------------------------------------- reading


@dataclass(frozen=True)
class Corpus:
    """Everything the pages show, read once."""

    arms: dict[int, dict[str, dict[str, Any]]]
    frame_dirs: dict[int, Path]
    truth: dict[str, dict[str, Any]]
    sessions: dict[str, dict[str, Any]]
    no_ruling: list[dict[str, Any]]
    refused_sessions: list[str]
    mark4: dict[int, dict[str, Any] | None]
    bundles: dict[int, dict[str, dict[str, Any]]]
    ledger: Path


def _bundles(preds: Path, lines: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Each line's record bundle, `<preds>.record/<record>.json`, by ruling id."""
    out = {}
    for did, line in lines.items():
        rec = line.get("record")
        if not isinstance(rec, str) or not re.fullmatch(r"[0-9a-f]{64}", rec):
            raise CardError(f"{preds}: ruling {did} names no record.")
        path = Path(f"{preds}.record") / f"{rec}.json"
        try:
            bundle = score._read_json(_need(path))
        except score.ScoreError as exc:
            raise CardError(str(exc)) from None
        if not isinstance(bundle, dict):
            raise CardError(f"{path}: not a JSON object.")
        out[did] = bundle
    return out


def _need(path: Path) -> Path:
    if not path.is_file():
        raise CardError(f"{path}: not found.")
    return path


def _contact_lines(path: Path) -> dict[str, dict[str, Any]]:
    try:
        lines, _ = score.read_preds([_need(path)])
    except score.ScoreError as exc:
        raise CardError(str(exc)) from None
    return {k: v for k, v in lines.items() if v["kind"] == "contact"}


def _mark4(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        m4 = score._read_json(path).get("mark_4")
    except (score.ScoreError, AttributeError):
        raise CardError(f"{path}: not a score file.") from None
    return m4 if isinstance(m4, dict) and m4.get("status") == "scored" else None


def load_corpus(data: Path, limits: Path) -> Corpus:
    """Read the private folder; raise CardError naming the file on anything missing or bad."""
    arms = {arm: _contact_lines(data / f"preds-arm{arm}.jsonl") for arm in ARMS}
    if not arms[2]:
        raise CardError(f"{data / 'preds-arm2.jsonl'}: no contact lines.")
    try:
        truth = score.read_truth(_need(data / "truth.json"))
        league = score._read_json(_need(data / "league.json"))
        labels = score._labels(league, data / "league.json")
        inputs = score._read_json(_need(data / "inputs.json"))
        if not isinstance(inputs, dict) or "catalogue" not in inputs:
            raise CardError(f"{data / 'inputs.json'}: no `catalogue`.")
        catalogue = score._read_json(_need(Path(inputs["catalogue"])))
        limit_lines, _ = score.read_preds([_need(limits)])
        m1 = score.mark1(limit_lines, league, catalogue, labels)
    except score.ScoreError as exc:
        raise CardError(str(exc)) from None
    if m1["status"] != "scored":
        raise CardError(f"{limits}: {m1['status']}.")
    for did, line in arms[2].items():
        if did not in truth:
            raise CardError(f"{data / 'truth.json'}: decision {did} is missing.")
        session = (line.get("window") or {}).get("session")
        if session not in league["sessions"]:
            raise CardError(f"ruling {did}: session not in league.json.")
    return Corpus(
        arms=arms,
        frame_dirs={arm: data / f"preds-arm{arm}.jsonl{pitbot.FRAMES_SUFFIX}" for arm in ARMS},
        truth=truth,
        sessions=league["sessions"],
        no_ruling=m1["no_ruling_on_record"],
        refused_sessions=m1["refused_sessions"],
        mark4={arm: _mark4(data / f"score-arm{arm}.json") for arm in ARMS},
        bundles={arm: _bundles(data / f"preds-arm{arm}.jsonl", arms[arm]) for arm in ARMS},
        ledger=data / pitbot.LEDGER_NAME,
    )


def feed_names(data: Path) -> list[str]:
    """The adapter's lint names: every driver name in every session feed of league.json."""
    try:
        return pitbot._League(data / "league.json").all_names()
    except (pitbot.RacingCliError, OSError, ValueError) as exc:
        raise CardError(f"the names list could not be built: {exc}") from None


def league_banned(data: Path) -> list[str]:
    """The league's name: the pack folder's name and its `pack.json` name."""
    where = data / "inputs.json"
    banned: set[str] = set()
    try:
        inputs = score._read_json(where)
        pack_dir = Path(inputs.get("pack_dir") or "")
        if pack_dir.name:
            banned.add(pack_dir.name)
            where = pack_dir / "pack.json"
            if where.is_file():
                name = score._read_json(where).get("name") or ""
                if isinstance(name, str) and name:
                    banned.add(name)
    except score.ScoreError as exc:
        raise CardError(str(exc)) from None
    except (OSError, ValueError, TypeError, AttributeError):
        raise CardError(f"{where}: the league's name could not be read.") from None
    if not banned:
        raise CardError(f"{data / 'inputs.json'}: no league name could be read from `pack_dir`.")
    return sorted(banned)


def gather_names(data: Path, known_names: Path | None) -> tuple[list[str], list[str]]:
    """The adapter's lint names plus `known_names`, and the league's banned names."""
    names = set(feed_names(data))
    if known_names is not None:
        try:
            text = known_names.read_text(encoding="utf-8")
        except OSError as exc:
            raise CardError(f"{known_names}: cannot be read ({exc.strerror}).") from None
        names.update(n.strip() for n in text.splitlines() if n.strip())
    if len(names) < 10:
        raise CardError("the names list holds almost no names; the feed reader is broken.")
    return sorted(names), league_banned(data)


# ---------------------------------------------------------------- the lint


class _Visible(HTMLParser):
    """Collect what a viewer reads: text outside <style>, plus `alt` and `title` values."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "script"):
            self._skip += 1
        for key, value in attrs:
            if key in ("alt", "title") and value:
                self.parts.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip and data.strip():
            self.parts.append(data)


def visible_text(page: str) -> str:
    parser = _Visible()
    parser.feed(page)
    parser.close()
    return "\n".join(parser.parts)


def check_page(name: str, page: str, names: list[str], banned: list[str]) -> None:
    """Raise CardError when the page's visible text holds a name or the league's name."""
    text = visible_text(page)
    try:
        lint.assert_clean(text, names=names, extra_banned=banned, allow=pitbot.ALLOW)
    except lint.LintError as exc:
        raise CardError(f"{name}: refused, not written. {exc}") from None
    squashed = re.sub(r"\s+", "", text).casefold()
    if any(re.sub(r"\s+", "", b).casefold() in squashed for b in banned):
        raise CardError(f"{name}: refused, not written: the league's name appears run together.")


# ---------------------------------------------------------------- rendering

CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
body { margin: 0; background: #0b0e13; color: #e8ecf1;
  font: 18px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
main { max-width: 1680px; margin: 0 auto; padding: 40px 48px 64px; }
header { border-bottom: 1px solid #263040; padding-bottom: 20px; margin-bottom: 28px; }
.kicker { color: #f2b544; font-weight: 600; letter-spacing: .08em; text-transform: uppercase;
  font-size: 14px; margin: 0 0 6px; }
h1 { font-size: 44px; line-height: 1.1; margin: 0 0 8px; }
h2 { font-size: 22px; margin: 36px 0 12px; color: #c9d3df; }
.meta { color: #9fb0c3; font-size: 20px; margin: 0; }
.meta b { color: #e8ecf1; font-weight: 600; }
table { border-collapse: collapse; font-size: 18px; min-width: 640px; }
th, td { text-align: left; padding: 10px 18px; border-bottom: 1px solid #263040; }
th { color: #9fb0c3; font-weight: 600; font-size: 15px; text-transform: uppercase;
  letter-spacing: .05em; }
td.num { font-variant-numeric: tabular-nums; }
tr.final td { color: #f2b544; font-weight: 600; }
.none { color: #8492a6; font-style: italic; }
.note { color: #8492a6; font-size: 16px; margin: 10px 0 0; }
.strip { display: grid; grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
  gap: 14px; }
figure { margin: 0; background: #131923; border: 2px solid #1c2430; border-radius: 6px;
  overflow: hidden; }
figure.moment { border-color: #f2b544; }
figure img { display: block; width: 100%; height: auto; }
figcaption { display: flex; gap: 12px; align-items: baseline; padding: 8px 12px;
  font-size: 16px; font-variant-numeric: tabular-nums; color: #c9d3df; }
figcaption .rel { color: #8492a6; }
.tag { margin-left: auto; font-size: 13px; padding: 2px 8px; border-radius: 4px;
  background: #1f2a3a; color: #9fc3ff; }
figure.moment .tag.m { background: #f2b544; color: #0b0e13; }
.cars { display: flex; flex-wrap: wrap; gap: 10px; padding: 0; margin: 0; list-style: none; }
.cars li { background: #1a2230; border: 1px solid #2c3a50; border-radius: 6px;
  padding: 6px 16px; font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
ol.facts { margin: 0; padding-left: 26px; color: #d3dbe5; }
ol.facts li { margin: 4px 0; }
blockquote { margin: 0; padding: 16px 22px; border-left: 4px solid #f2b544;
  background: #131923; font-size: 22px; }
ul.log li { margin: 6px 0; }
code { background: #1f2a3a; padding: 1px 6px; border-radius: 4px; font-size: 0.92em; }
a { color: #9fc3ff; }
.grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 36px; }
@media (max-width: 1100px) { .grid2 { grid-template-columns: 1fr; } }
"""


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, body: str) -> str:
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{esc(title)}</title>\n<style>{CSS}</style>\n</head>\n"
        f"<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def _num(x: float) -> str:
    return f"{x:g}" if float(x) != int(x) else str(int(x))


def _secs(x: float) -> str:
    return f"{float(x):.1f}"


def model_label(read: dict[str, Any] | None, arm: int) -> str:
    model = (read or {}).get("model")
    short = MODEL_LABELS.get(model or "", (model or "").rsplit("/", 1)[-1] or "model")
    return f"Arm {arm} ({short})"


def read_cells(read: dict[str, Any] | None) -> tuple[str, str]:
    """The verdict and car cells of one model's read, as HTML."""
    if not read or read.get("agreed") is not True:
        detail = ""
        if read:
            runs, fails = read.get("runs"), read.get("parse_failures")
            if isinstance(runs, int) and runs and fails == runs:
                detail = f" (no text, {runs} of {runs} runs)"
            elif isinstance(runs, int) and runs:
                detail = " (runs disagree)"
        return f'<span class="none">{NO_READ}{esc(detail)}</span>', '<span class="none">-</span>'
    verdict = VERDICT_WORDS.get(str(read.get("verdict")), str(read.get("verdict")))
    runs = read.get("runs")
    agreed = f", agreed over {runs} runs" if isinstance(runs, int) else ""
    car = read.get("offender")
    car_cell = esc(car) if car else '<span class="none">no car named</span>'
    return esc(verdict + agreed), car_cell


def verdict_table(corpus: Corpus, did: str) -> str:
    rows = []
    for arm in ARMS:
        line = corpus.arms[arm].get(did)
        read = (line or {}).get("model_read") or None
        v, c = read_cells(read)
        rows.append(
            f"<tr><td>The model's read, {esc(model_label(read, arm))}</td><td>{v}</td>"
            f'<td class="num">{c}</td></tr>'
        )
    t = corpus.truth[did]
    verdict = VERDICT_WORDS.get(str(t.get("verdict")), str(t.get("verdict")))
    car = esc(t["offender_sim"]) if t["offender_sim"] else '<span class="none">none</span>'
    other = f" (contact with {esc(t['victim_sim'])})" if t["victim_sim"] else ""
    rows.append(
        f'<tr class="final"><td>The steward\'s final</td><td>{esc(verdict)}</td>'
        f'<td class="num">{car}{other}</td></tr>'
    )
    notes = [f'<p class="note">{esc(READ_NOTE)}</p>']
    marks = []
    for arm in ARMS:
        m4 = corpus.mark4.get(arm)
        if m4:
            marks.append((arm, m4))
    if marks:
        parts = [f"arm {arm}, {m['numerator']} of {m['denominator']}" for arm, m in marks]
        first = marks[0][1]
        results = {bool(m["pass"]) for _, m in marks}
        if len(results) == 1:
            word = "pass" if results.pop() else "fail"
            outcome = f"{word} on both" if len(marks) == 2 else word
        else:
            outcome = ", ".join(f"arm {arm} {'pass' if m['pass'] else 'fail'}" for arm, m in marks)
        notes.append(
            f'<p class="note">Mark 4, offender named and right: {esc("; ".join(parts))};'
            f" the mark is {esc(first['pass_at'])} of {esc(first['denominator'])}"
            f" ({esc(outcome)}).</p>"
        )
    return (
        "<table><thead><tr><th>Source</th><th>Verdict</th><th>Car</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table>"
        + "".join(notes)
    )


def _frame_bytes(corpus: Corpus, sha: str) -> bytes:
    for arm in ARMS:
        path = corpus.frame_dirs[arm] / f"{sha}.jpg"
        if path.is_file():
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != sha:
                raise CardError(f"{path}: the frame does not hash to its name.")
            if raw[:3] != b"\xff\xd8\xff":
                raise CardError(f"{path}: not a JPEG.")
            return raw
    raise CardError(f"frame {sha[:12]}: not in any arm's frames folder.")


def moment(corpus: Corpus, did: str) -> tuple[float, float] | None:
    """The steward's moment as recorded by arm 2's run: (feed second, stream second).

    From the bundle: `inputs.moment.te` and `detail.frames.centre_s`. None on a line the run
    built around the locator's window (no `moment` input): such a card marks no centre.
    """
    bundle = corpus.bundles[2][did]
    given = (bundle.get("inputs") or {}).get("moment")
    if not given:
        return None
    frames = (bundle.get("detail") or {}).get("frames") or {}
    te, centre_s, centre_te = given.get("te"), frames.get("centre_s"), frames.get("centre_te")
    if not isinstance(te, int | float) or not isinstance(centre_s, int | float):
        raise CardError(f"ruling {did}: the record gives a moment but no centre second.")
    if centre_te != te:
        raise CardError(f"ruling {did}: the record's moment and frame centre disagree.")
    return float(te), float(centre_s)


def sent_shas(corpus: Corpus, arm: int, did: str) -> list[str] | None:
    """The frame hashes the run recorded as sent to the model (`model_call.frame_sha256`)."""
    bundle = corpus.bundles[arm].get(did)
    call = ((bundle or {}).get("inputs") or {}).get("model_call")
    if not isinstance(call, dict):
        return None
    shas = call.get("frame_sha256")
    if not isinstance(shas, list) or not all(isinstance(s, str) for s in shas):
        raise CardError(f"ruling {did}: arm {arm}'s record holds no list of sent frames.")
    return shas


def frame_strip(corpus: Corpus, did: str) -> str:
    line = corpus.arms[2][did]
    frames = sorted(line.get("frames") or [], key=lambda f: (float(f["stream_s"]), f["sha256"]))
    if not frames:
        return '<p class="none">No frames on this line.</p>'
    at = moment(corpus, did)
    centre = None if at is None else at[1]
    sent = sent_shas(corpus, 2, did)
    sent_set = set(sent or [])
    on_line = {f["sha256"] for f in frames}
    if not sent_set <= on_line:
        raise CardError(f"ruling {did}: the record sent a frame that is not on the line.")
    figs = []
    for f in frames:
        s = float(f["stream_s"])
        tags = []
        rel_html = ""
        at_moment = False
        if centre is not None:
            rel = round(s - centre, 1)
            at_moment = abs(rel) < 0.25
            rel_text = "the moment" if at_moment else f"{rel:+.1f} s"
            rel_html = f'<span class="rel">{rel_text}</span>'
        if at_moment:
            tags.append('<span class="tag m">steward\'s moment</span>')
        if f["sha256"] in sent_set:
            tags.append('<span class="tag">sent to the model</span>')
        data = base64.b64encode(_frame_bytes(corpus, f["sha256"])).decode("ascii")
        figs.append(
            f'<figure class="{"moment" if at_moment else "frame"}">'
            f'<img src="data:image/jpeg;base64,{data}" alt="Stream second {_secs(s)}">'
            f"<figcaption><b>stream {_secs(s)} s</b>"
            f"{rel_html}{''.join(tags)}</figcaption></figure>"
        )
    if sent is None:
        sent_note = "no model call on record"
    else:
        other = sent_shas(corpus, 1, did)
        where = "on each arm" if other is None or other == sent else "on arm 2"
        sent_note = f"{len(sent)} sent to the model {where}"
    if centre is None:
        sent_note += "; no steward's moment on this line"
    return (
        f'<p class="note">{len(frames)} frames; {esc(sent_note)}.</p>\n'
        f'<div class="strip">{"".join(figs)}</div>'
    )


def _session(corpus: Corpus, line: dict[str, Any]) -> dict[str, Any]:
    return corpus.sessions[line["window"]["session"]]


def card_header(corpus: Corpus, did: str, kicker: str) -> str:
    line = corpus.arms[2][did]
    s = _session(corpus, line)
    lap = line["window"].get("lap")
    lap_text = f"Lap {lap}" if lap is not None else "Lap not stated"
    return (
        f'<header><p class="kicker">{esc(kicker)}</p><h1>Decision {esc(did)}</h1>'
        f'<p class="meta"><b>{esc(s["track"])}</b> · {esc(s["session"])} · {esc(lap_text)}</p>'
        "</header>"
    )


def contact_card(corpus: Corpus, did: str) -> str:
    line = corpus.arms[2][did]
    w = line["window"]
    te0, te1 = w["te"]
    s0, s1 = w["stream_s"]
    at = moment(corpus, did)
    moment_cell = (
        "none on this line (the locator's window)"
        if at is None
        else f"feed {_num(at[0])}, stream {_secs(at[1])}"
    )
    lap = w.get("lap")
    cands = sorted(line.get("candidates") or [], key=score.numkey)
    facts = line.get("facts") or []
    body = [
        card_header(corpus, did, "Contact protest · evidence card"),
        "<h2>The verdicts</h2>",
        verdict_table(corpus, did),
        "<h2>The frames</h2>",
        frame_strip(corpus, did),
        '<div class="grid2"><section>',
        "<h2>The window</h2>",
        "<table><tbody>"
        f'<tr><td>Feed seconds</td><td class="num">{_num(te0)} to {_num(te1)}</td></tr>'
        f'<tr><td>Stream seconds</td><td class="num">{_secs(s0)} to {_secs(s1)}</td></tr>'
        f'<tr><td>Steward\'s moment</td><td class="num">{esc(moment_cell)}</td></tr>'
        f'<tr><td>Lap</td><td class="num">{esc(lap if lap is not None else "not stated")}'
        "</td></tr></tbody></table>",
        "<h2>The closed candidate set</h2>",
        '<ul class="cars">' + "".join(f"<li>{esc(c)}</li>" for c in cands) + "</ul>"
        if cands
        else '<p class="none">The set is empty.</p>',
        "</section><section>",
        "<h2>The facts</h2>",
        '<ol class="facts">' + "".join(f"<li>{esc(f)}</li>" for f in facts) + "</ol>"
        if facts
        else '<p class="none">No facts on this line.</p>',
        "</section></div>",
    ]
    if did in FRAME_LOOK:
        body += [
            "<h2>The frame look</h2>",
            f"<blockquote>{esc(FRAME_LOOK[did])}</blockquote>",
            f'<p class="note">{esc(FRAME_LOOK_NOTE)}</p>',
        ]
    return page(f"Decision {did}", "\n".join(body))


def _plain(text: str) -> str:
    """A LOG sentence for the screen: a `backticked` verdict token reads as plain words."""
    return esc(re.sub(r"`([^`]+)`", lambda m: VERDICT_WORDS.get(m[1], m[1]), text))


def honesty_card(corpus: Corpus) -> str:
    did = HONESTY_ID
    body = [
        card_header(corpus, did, "Honesty card"),
        "<h2>The frame look</h2>",
        f"<blockquote>{esc(FRAME_LOOK[did])}</blockquote>",
        f'<p class="note">{esc(FRAME_LOOK_NOTE)}</p>',
        "<h2>The model's read beside it</h2>",
        verdict_table(corpus, did),
        "<h2>What this shows</h2>",
        '<ul class="log">' + "".join(f"<li>{_plain(t)}</li>" for t in HONESTY_LINES) + "</ul>",
        "<h2>The frames</h2>",
        frame_strip(corpus, did),
    ]
    return page(f"Decision {did}, honesty card", "\n".join(body))


def run_reads(corpus: Corpus, arm: int, did: str) -> list[tuple[str, str | None] | None]:
    """Each recorded run's checked reply as (verdict, offender), None for a failed run.

    The replies are read from the ledger under the bundle's `ledger_keys` and judged with the
    same `faultline.ruling.validate` the run used, against the call's candidates and labels.
    Only the verdict and the car are kept; no reply text is shown.
    """
    inputs = (corpus.bundles[arm].get(did) or {}).get("inputs") or {}
    call, keys = inputs.get("model_call"), inputs.get("ledger_keys")
    if not isinstance(call, dict) or not isinstance(keys, list) or not keys:
        raise CardError(f"ruling {did}: arm {arm}'s record holds no model call to check.")
    ledger = Ledger(corpus.ledger)
    out: list[tuple[str, str | None] | None] = []
    for key in keys:
        try:
            entry = ledger.get(key)
        except LedgerError as exc:
            raise CardError(
                f"ruling {did}: arm {arm}'s ledger entry is unreadable: {exc}"
            ) from None
        if entry is None:
            raise CardError(f"ruling {did}: arm {arm}'s reply {key[:12]} is not in the ledger.")
        run = modelread.validate(
            str(entry.get("reply", "")), call["candidates"], call["frame_labels"], pitbot.VERDICTS
        )
        out.append(None if run is None else (run["verdict"], run["offender"]))
    return out


def check_honesty(corpus: Corpus) -> None:
    """Refuse the honesty card unless the data holds what its LOG sentences claim."""
    did = HONESTY_ID

    def refuse(claim: str) -> CardError:
        return CardError(
            f"honesty-{did}.html: refused, the data does not hold the LOG's claim: {claim}"
        )

    claim2, claim1, claim_steward = HONESTY_LINES[1], HONESTY_LINES[2], HONESTY_LINES[4]
    read2 = (corpus.arms[2].get(did) or {}).get("model_read") or {}
    runs2 = run_reads(corpus, 2, did) if read2 else []
    if not (
        read2.get("agreed") is True
        and read2.get("verdict") == "not_visible"
        and read2.get("offender") is None
        and read2.get("runs") == 3
        and runs2 == [("not_visible", None)] * 3
    ):
        raise refuse(claim2)
    read1 = (corpus.arms[1].get(did) or {}).get("model_read") or {}
    runs1 = run_reads(corpus, 1, did) if read1 else []
    if not (
        read1.get("agreed") is False
        and read1.get("runs") == 3
        and None not in runs1
        and sorted(runs1, key=repr)
        == sorted([("not_visible", None), ("not_visible", None), ("penalty", "5")], key=repr)
    ):
        raise refuse(claim1)
    if corpus.truth[did].get("offender_sim") != "5":
        raise refuse(claim_steward)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def over_limit_groups(corpus: Corpus) -> list[tuple[str, str, list[dict[str, Any]]]]:
    """(track, session, breaches) in racing_score's order: race day, heat before feature."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for b in corpus.no_ruling:
        groups.setdefault((b["track"], b["session"]), []).append(b)
    return [(t, s, rows) for (t, s), rows in groups.items()]


def over_limit_page(track: str, session: str, rows: list[dict[str, Any]]) -> str:
    trs = "".join(
        f'<tr><td class="num">{esc(b["car"])}</td><td class="num">{esc(b["total"])}</td>'
        f'<td class="num">{esc(b["limit"])}</td><td class="num">{esc(b["clause"])}</td></tr>'
        for b in sorted(rows, key=lambda b: score.numkey(b["car"]))
    )
    body = (
        f'<header><p class="kicker">Incident limit</p><h1>{esc(NO_RULING_TITLE)}</h1>'
        f'<p class="meta"><b>{esc(track)}</b> · {esc(session)} · {len(rows)}'
        f" car{'s' if len(rows) != 1 else ''}</p></header>\n"
        f"<p>{esc(NO_RULING_LEAD)}</p>\n"
        "<table><thead><tr><th>Car</th><th>Total</th><th>Limit</th><th>Clause</th></tr></thead>"
        f"<tbody>{trs}</tbody></table>"
    )
    return page(NO_RULING_TITLE, body)


def index_page(
    corpus: Corpus, contact: list[tuple[str, str]], over: list[tuple[str, str, str, int]]
) -> str:
    items = []
    for did, name in contact:
        s = _session(corpus, corpus.arms[2][did])
        t = corpus.truth[did]
        final = VERDICT_WORDS.get(str(t.get("verdict")), str(t.get("verdict")))
        car = f", car {t['offender_sim']}" if t["offender_sim"] else ""
        items.append(
            f'<tr><td><a href="{esc(name)}">Decision {esc(did)}</a></td>'
            f"<td>{esc(s['track_short'])} {esc(s['session'])}</td>"
            f"<td>{esc(final + car)}</td></tr>"
        )
    contact_html = (
        "<table><thead><tr><th>Card</th><th>Session</th><th>Steward's final</th></tr></thead>"
        f"<tbody>{''.join(items)}</tbody></table>"
    )
    over_rows = "".join(
        f'<tr><td><a href="{esc(name)}">{esc(track)} {esc(session)}</a></td>'
        f'<td class="num">{n}</td></tr>'
        for name, track, session, n in over
    )
    total = sum(n for *_, n in over)
    refused = (
        f'<p class="note">Not ruled, no counter shown: {esc(", ".join(corpus.refused_sessions))}.'
        "</p>"
        if corpus.refused_sessions
        else ""
    )
    honesty = (
        f'<ul><li><a href="honesty-{HONESTY_ID}.html">Decision {HONESTY_ID}: the model\'s read'
        " beside the frame look</a></li></ul>"
        if HONESTY_ID in corpus.arms[2]
        else ""
    )
    body = (
        '<header><p class="kicker">Racing evidence</p><h1>Evidence cards</h1>'
        f'<p class="meta">{len(contact)} contact protests · {total} cars over the limit with no'
        " ruling on record</p></header>\n"
        f"<h2>Contact protests</h2>{contact_html}\n"
        f"<h2>{esc(NO_RULING_TITLE)}</h2>"
        "<table><thead><tr><th>Session</th><th>Cars</th></tr></thead>"
        f"<tbody>{over_rows}</tbody></table>{refused}\n"
        f"<h2>Honesty card</h2>{honesty}"
    )
    return page("Evidence cards", body)


# ---------------------------------------------------------------- building and writing


def build(corpus: Corpus, names: Iterable[str], banned: Iterable[str]) -> dict[str, str]:
    """Every page by file name, each checked by the lint; raise CardError on the first hit."""
    names, banned = list(names), list(banned)
    pages: dict[str, str] = {}
    contact = []
    for did in sorted(corpus.arms[2], key=score.numkey):
        name = f"decision-{did}.html"
        pages[name] = contact_card(corpus, did)
        contact.append((did, name))
    over = []
    for track, session, rows in over_limit_groups(corpus):
        name = f"over-limit-{_slug(track)}-{_slug(session)}.html"
        pages[name] = over_limit_page(track, session, rows)
        over.append((name, track, session, len(rows)))
    if HONESTY_ID in corpus.arms[2]:
        check_honesty(corpus)
        pages[f"honesty-{HONESTY_ID}.html"] = honesty_card(corpus)
    pages["index.html"] = index_page(corpus, contact, over)
    for name, text in pages.items():
        check_page(name, text, names, banned)
    return pages


def write_pages(out: Path, pages: dict[str, str]) -> None:
    """Clear stale pages, then write each page atomically.

    Every `*.html` directly in `out` that this run does not write is removed, and every stale
    `*.tmp`; nothing else in `out` and nothing in a subfolder is touched.
    """
    out.mkdir(parents=True, exist_ok=True)
    for path in sorted([*out.glob("*.html"), *out.glob("*.tmp")]):
        if path.is_file() and not (path.suffix == ".html" and path.name in pages):
            path.unlink()
    for name in sorted(pages):
        path = out / name
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(pages[name].encode("utf-8"))
        os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", default=str(REPO / "data" / "racing"), help="the private folder")
    ap.add_argument("--out", default=None, help="the cards folder (default <data>/cards)")
    ap.add_argument("--limits", default=None, help="limits output (default <data>/limits-a.jsonl)")
    ap.add_argument("--known-names", type=Path, default=None, help="more names, one per line")
    args = ap.parse_args(argv)
    data = Path(args.data)
    out = Path(args.out) if args.out else data / "cards"
    limits = Path(args.limits) if args.limits else data / "limits-a.jsonl"
    for need in ("preds-arm2.jsonl", "truth.json", "league.json"):
        if not (data / need).is_file():
            print(
                f"racing_card: private corpus absent ({need} not found in {data});"
                " nothing written.",
                file=sys.stderr,
            )
            return 1
    try:
        corpus = load_corpus(data, limits)
        names, banned = gather_names(data, args.known_names)
        pages = build(corpus, names, banned)
        write_pages(out, pages)
    except CardError as exc:
        print(f"racing_card: {exc}", file=sys.stderr)
        return 1
    contact = sum(n.startswith("decision-") for n in pages)
    over = [n for n in pages if n.startswith("over-limit-")]
    honesty = sum(n.startswith("honesty-") for n in pages)
    print(
        f"racing_card: {len(pages)} pages in {out}: {contact} contact cards, {len(over)}"
        f" over-limit pages ({len(corpus.no_ruling)} cars), {honesty} honesty card, index"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
