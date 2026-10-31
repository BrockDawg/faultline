"""The three-minute walk: one static page from the 26-clip smoke and the shift, and one still per
line of the walk.

`faultline demo --smoke <smoke dir> --shift <shift dir> --rules <pack dir> --out <page.html>` builds
the page:
the rules pack as the site wrote it, then three clips (one breach with the number that decided it,
one clear, one unable naming the fact it lacks), each with its frames, its measurement and its
ruling, then the words a model wrote beside one ruling (from the recorded notes only, never the
ruling), then the shift's count of breach, clear and unable by rule, then one replay proof (the
smoke's rulings and their offline rebuild, the same bytes, the hash shown).

The page is a pure function of its input files: no clock, no network, no script, no outside URL; the
frames are embedded as data. Two builds are byte-identical.

`faultline demo --stills <SCRIPT.md> --page <page.html> --out <STILLS dir>` renders one PNG per line
of the walk from the page itself: each script line names the panel on screen as `(on screen: pNN)`,
and the panel's elements marked `data-s` are drawn by ffmpeg (the judge's own decoder) onto a
1920x1080 still. No browser, no outside service.
No model is called by either command.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path

from faultline.adapters.video.dashboard import FACT_WORDS, decided_by, lacks
from faultline.adapters.video.shift import TITLES, ruling_frames

SRC_FPS = 24  # the shift's frame names count the clip's own 24 fps frames from the window start

# the three clips of the walk: (kind, clip stem, rule). Fixed before the first build
# (dev/demo/PASS_MARKS.md).
PICKS = [
    ("breach", "blind_corner_no_vest_07", "hi_vis_in_truck_zone"),
    ("clear", "spotter_ahead_01", "hi_vis_in_truck_zone"),
    ("unable", "vest_group_cross_10", "pedestrian_separation"),
]
VERDICT_OF = {"breach": "breach", "clear": "clear", "unable": "unable_to_rule"}
WORDS_PICK = 0  # the words panel shows the recorded note beside the breach's ruling

# a missing fact in the words of the rulings (30 Oct): the camera gate's own sentence
FACT_SAY = dict(FACT_WORDS)
FACT_SAY["camera.static"] = "the camera moved; this judge reads fixed site cameras"


class DemoError(RuntimeError):
    pass


# ---------------------------------------------------------------- inputs


def _jsonl(p: Path) -> list[dict]:
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def read_pack(pack_dir: Path) -> list[dict]:
    """The pack's rules as the site wrote them: id, title, the rule's sentences, the 'On video'
    sentence, the source.
    """
    rules = []
    for f in sorted(Path(pack_dir).glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        t = f.read_text(encoding="utf-8")
        m = re.match(r"^---\n(.*?)\n---\n(.*)$", t.replace("\r\n", "\n"), re.S)
        if not m:
            continue
        head = dict(ln.split(":", 1) for ln in m.group(1).splitlines() if ":" in ln)
        body = [" ".join(p.split()) for p in m.group(2).strip().split("\n\n") if p.strip()]
        on_video = next(
            (p[len("On video:") :].strip() for p in body if p.startswith("On video:")), ""
        )
        source = next((p[len("Source:") :].strip() for p in body if p.startswith("Source:")), "")
        rule = " ".join(p for p in body if not p.startswith(("On video:", "Source:")))
        rules.append(
            {
                "id": head["id"].strip(),
                "title": head["title"].strip(),
                "rule": rule,
                "on_video": on_video,
                "source": source,
                "text": m.group(2),
            }
        )
    if not rules:
        raise DemoError(f"no rule files in {pack_dir}")
    return rules


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _frames_of(shift_dir: Path, window: str, ruling: dict) -> list[tuple[int, str]]:
    """The frames the ruling names (at most three, as the dashboard picks them); with none named,
    every frame the shift kept for the window. Each as (frame index, data URI)."""
    fdir = shift_dir / "frames"
    named = [i for i in ruling_frames(ruling) if (fdir / f"{window}-{i:04d}.jpg").is_file()]
    if not named:
        named = sorted(int(p.stem.rsplit("-", 1)[1]) for p in fdir.glob(f"{window}-*.jpg"))
    out = []
    for i in named:
        b = (fdir / f"{window}-{i:04d}.jpg").read_bytes()
        out.append((i, "data:image/jpeg;base64," + base64.b64encode(b).decode("ascii")))
    return out


def gather(smoke_dir: Path, shift_dir: Path, pack_dir: Path) -> dict:
    smoke_dir, shift_dir = Path(smoke_dir), Path(shift_dir)
    preds_p, replay_p = smoke_dir / "preds.jsonl", smoke_dir / "replay.jsonl"
    for p in (preds_p, replay_p, shift_dir / "windows.jsonl", shift_dir / "preds.jsonl"):
        if not p.is_file():
            raise DemoError(f"missing input: {p.name} in {p.parent.name}")
    smoke = {p["id"]: p for p in _jsonl(preds_p)}
    windows = _jsonl(shift_dir / "windows.jsonl")
    shift_preds = {p["id"]: p for p in _jsonl(shift_dir / "preds.jsonl")}
    words_p = shift_dir / "preds.words.jsonl"
    words = {w["id"]: w for w in _jsonl(words_p)} if words_p.is_file() else {}
    pack = read_pack(pack_dir)
    pack_titles = {r["id"]: r["title"] for r in pack}

    picks = []
    for kind, stem, rule in PICKS:
        sp = smoke.get(stem)
        if sp is None:
            raise DemoError(f"{stem} is not in the smoke")
        r = next((x for x in sp["rulings"] if x["rule"] == rule), None)
        if r is None or r["verdict"] != VERDICT_OF[kind]:
            raise DemoError(
                f"{stem} {rule}: the smoke rules {r and r['verdict']}, the walk needs "
                f"{VERDICT_OF[kind]}"
            )
        w = next((x for x in windows if Path(x["clip"]).stem == stem), None)
        if w is None:
            raise DemoError(f"{stem} is not in the shift")
        shr = next(x for x in shift_preds[w["window"]]["rulings"] if x["rule"] == rule)
        for k in ("verdict", "missing_fact", "evidence", "frames"):
            if shr.get(k) != r.get(k):
                raise DemoError(f"{stem} {rule}: the shift's {k} differs from the smoke's")
        others = [
            {"rule": x["rule"], "title": TITLES.get(x["rule"], x["rule"]), "verdict": x["verdict"]}
            for x in sp["rulings"]
            if x["rule"] != rule
        ]
        note = None
        wl = words.get(w["window"])
        if wl:
            for x in wl.get("rulings", []):
                if x["rule"] == rule and x.get("verdict") == r["verdict"] and x.get("note"):
                    note = x["note"]
        picks.append(
            {
                "kind": kind,
                "clip": stem,
                "rule": rule,
                "title": pack_titles.get(rule, TITLES.get(rule, rule)),
                "verdict": r["verdict"],
                "evidence": r["evidence"],
                "missing_fact": r["missing_fact"],
                "lacks": lacks(r["missing_fact"], rule, pack)
                if r["verdict"] == "unable_to_rule"
                else None,
                "decided": decided_by(rule, r["evidence"]) if r["verdict"] == "breach" else None,
                "frames": _frames_of(shift_dir, w["window"], r),
                "record": sp["record"],
                "others": others,
                "note": note,
            }
        )
    if picks[WORDS_PICK]["note"] is None:
        raise DemoError("the words panel's note is not recorded beside its ruling")

    # the shift's count by rule, pack order first
    order = [r["id"] for r in pack]
    for p in shift_preds.values():
        for r in p["rulings"]:
            if r["rule"] not in order:
                order.append(r["rule"])
    counts = {rid: {"breach": 0, "clear": 0, "unable_to_rule": 0} for rid in order}
    facts: dict[str, int] = {}
    for w in windows:
        for r in shift_preds[w["window"]]["rulings"]:
            counts[r["rule"]][r["verdict"]] += 1
            if r["verdict"] == "unable_to_rule":
                facts[r["missing_fact"]] = facts.get(r["missing_fact"], 0) + 1
    in_pack = {r["id"] for r in pack}
    rows = [
        {"rule": rid, "title": TITLES.get(rid, rid), "in_pack": rid in in_pack, **counts[rid]}
        for rid in order
    ]

    a, b = _sha(preds_p), _sha(replay_p)
    return {
        "pack": pack,
        "picks": picks,
        "rows": rows,
        "facts": sorted(facts.items(), key=lambda kv: (-kv[1], kv[0])),
        "windows": len(windows),
        "smoke_lines": len(smoke),
        "replay": {
            "preds_sha": a,
            "replay_sha": b,
            "same": preds_p.read_bytes() == replay_p.read_bytes(),
            "lines": len(smoke),
        },
    }


# ---------------------------------------------------------------- page


def _e(s) -> str:
    return html.escape(str(s), quote=True)


def _s(role: str, tag: str, text: str, cls: str = "", extra: str = "") -> str:
    c = f' class="{cls}"' if cls else ""
    return f'<{tag}{c} data-s="{role}"{extra}>{_e(text)}</{tag}>'


BADGE = {"breach": "Breach", "clear": "Clear", "unable_to_rule": "Unable to rule"}
VCLASS = {"breach": "breach", "clear": "clear", "unable_to_rule": "unable"}


def _panel(pid: str, name: str, inner: str) -> str:
    return f'<section class="panel" id="{pid}" data-name="{_e(name)}">\n{inner}\n</section>'


def _imgs(frames: list[tuple[int, str]]) -> str:
    cells = []
    for i, src in frames:
        cap = f"frame {i} · {i / SRC_FPS:.2f} s"
        cells.append(
            f'<figure><img src="{src}" alt="{_e(cap)}" data-s="img" data-cap="{_e(cap)}">'
            f"<figcaption>{_e(cap)}</figcaption></figure>"
        )
    return '<div class="frames">' + "".join(cells) + "</div>"


def _badge(verdict: str) -> str:
    return _s("badge-" + VCLASS[verdict], "div", BADGE[verdict], cls="badge " + VCLASS[verdict])


def panels(d: dict) -> list[str]:
    br, cl, un = d["picks"]
    out = []
    out.append(
        _panel(
            "p01",
            "title",
            "\n".join(
                [
                    _s("kicker", "p", "A rules judge for video", cls="kicker"),
                    _s("head", "h1", "faultline"),
                    _s(
                        "text",
                        "p",
                        "A site's rules pack and its camera footage go in. Rulings come "
                        "out, each with the rule, the frames "
                        "and the number that decided it.",
                        cls="lede",
                    ),
                    _s(
                        "text",
                        "p",
                        "Scripts measure and decide. A fact the scripts could not measure "
                        "makes the ruling "
                        "\u201cunable to rule\u201d, and the ruling names that fact.",
                    ),
                ]
            ),
        )
    )
    rules = []
    for r in d["pack"]:
        rules.append(
            f'<li><b data-s="text-b">{_e(r["title"])}</b>'
            + _s("text", "p", r["rule"])
            + _s("mono", "p", "On video: " + r["on_video"], cls="onvideo")
            + "</li>"
        )
    out.append(
        _panel(
            "p02",
            "rules-pack",
            "\n".join(
                [
                    _s("kicker", "p", "The rules pack, as the site wrote it", cls="kicker"),
                    _s("head", "h2", f"{len(d['pack'])} rules, one file each, in plain words"),
                    '<ol class="pack">' + "".join(rules) + "</ol>",
                ]
            ),
        )
    )
    out.append(
        _panel(
            "p03",
            "three-verdicts",
            "\n".join(
                [
                    _s("kicker", "p", "Three verdicts, never a guess", cls="kicker"),
                    _s("head", "h2", "Every rule gets one of three answers"),
                    '<div class="three">'
                    + _badge("breach")
                    + _s(
                        "text",
                        "p",
                        "the rule was broken, and the measured number that decided it is shown",
                    )
                    + _badge("clear")
                    + _s("text", "p", "the rule held, measured on the frames")
                    + _badge("unable_to_rule")
                    + _s("text", "p", "a fact was not measured, and the ruling names it")
                    + "</div>",
                ]
            ),
        )
    )
    # the breach
    out.append(
        _panel(
            "p04",
            "breach-frames",
            "\n".join(
                [
                    _s("kicker", "p", f"Clip {br['clip']}", cls="kicker"),
                    _s("head", "h2", br["title"]),
                    _imgs(br["frames"]),
                    _s("text", "p", "The frames the ruling names, straight from the clip."),
                ]
            ),
        )
    )
    out.append(
        _panel(
            "p05",
            "breach-ruling",
            "\n".join(
                [
                    _s("kicker", "p", f"Clip {br['clip']} · {br['title']}", cls="kicker"),
                    _badge(br["verdict"]),
                    _s("label", "p", "The number that decided it", cls="label"),
                    _s("decided", "p", br["decided"], cls="decided"),
                    _s("label", "p", "The measurement", cls="label"),
                    _s("mono", "p", br["evidence"], cls="evidence"),
                    _s("mono", "p", f"record {br['record']}", cls="hash"),
                ]
            ),
        )
    )
    out.append(
        _panel(
            "p06",
            "words-beside",
            "\n".join(
                [
                    _s("kicker", "p", "Words beside the ruling, never the ruling", cls="kicker"),
                    _s("head", "h2", "A model looked at the same frames and wrote this"),
                    _s("note", "blockquote", br["note"], cls="note"),
                    _s(
                        "text",
                        "p",
                        "The ruling was decided by the script's measurement. These words "
                        "sit beside it so a "
                        "person can check the frames faster; they never change a verdict.",
                    ),
                ]
            ),
        )
    )
    # the clear
    out.append(
        _panel(
            "p07",
            "clear",
            "\n".join(
                [
                    _s("kicker", "p", f"Clip {cl['clip']} · {cl['title']}", cls="kicker"),
                    _imgs(cl["frames"]),
                    _badge(cl["verdict"]),
                    _s("mono", "p", cl["evidence"], cls="evidence"),
                    _s(
                        "text",
                        "p",
                        "The other rules on this clip: "
                        + "; ".join(
                            f"{o['title']}, {BADGE[o['verdict']].lower()}" for o in cl["others"]
                        )
                        + ".",
                    ),
                ]
            ),
        )
    )
    # the unable
    out.append(
        _panel(
            "p08",
            "unable-frames",
            "\n".join(
                [
                    _s("kicker", "p", f"Clip {un['clip']}", cls="kicker"),
                    _s("head", "h2", un["title"]),
                    _imgs(un["frames"]),
                    _s(
                        "text",
                        "p",
                        "A group in vests crosses in front of the truck. The bottom of the "
                        "frame cuts the truck off, so where it meets "
                        "the floor is out of view.",
                    ),
                ]
            ),
        )
    )
    lk = un["lacks"] or {}
    out.append(
        _panel(
            "p09",
            "unable-ruling",
            "\n".join(
                [
                    _s("kicker", "p", f"Clip {un['clip']} · {un['title']}", cls="kicker"),
                    _badge(un["verdict"]),
                    _s("label", "p", "The fact it lacks", cls="label"),
                    _s("decided", "p", lk.get("words", un["missing_fact"]), cls="decided"),
                    *(
                        [
                            _s(
                                "mono",
                                "p",
                                "The pack's own words: \u201c" + lk["pack"] + "\u201d",
                                cls="evidence",
                            )
                        ]
                        if lk.get("pack")
                        else []
                    ),
                    _s("label", "p", "The measurement", cls="label"),
                    _s("mono", "p", un["evidence"], cls="evidence"),
                ]
            ),
        )
    )
    rows = []
    for r in d["rows"]:
        title = r["title"] + ("" if r["in_pack"] else " (this site's own extra rule)")
        txt = f"{title}: {r['breach']} breach, {r['clear']} clear, {r['unable_to_rule']} unable"
        rows.append(
            f'<tr data-s="row" data-text="{_e(txt)}"><th>{_e(title)}</th><td '
            f'class="breach">{r["breach"]}</td>'
            f'<td class="clear">{r["clear"]}</td><td class="unable">{r["unable_to_rule"]}</td></tr>'
        )
    top_fact, top_n = d["facts"][0] if d["facts"] else (None, 0)
    # The pack panel shows the site's written rules; a row the shift rules beyond them (the site
    # speed limit)
    # is named under the table, so the pack panel's count and the table's rows agree
    ords = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"]
    extra = [(i, r) for i, r in enumerate(d["rows"]) if not r["in_pack"]]
    caps = [
        f"The {ords[i] if i < len(ords) else str(i + 1) + 'th'} row, {r['title'].lower()}, "
        "is this site's own extra rule: "
        f"the shift rules it too, but it is not one of the {len(d['pack'])} rules in the "
        "pack shown before."
        for i, r in extra
    ]
    out.append(
        _panel(
            "p10",
            "shift",
            "\n".join(
                [
                    _s("kicker", "p", "One shift, every window ruled", cls="kicker"),
                    _s(
                        "head",
                        "h2",
                        f"{d['windows']} windows of footage, every rule answered on every window",
                    ),
                    '<table class="counts"><thead><tr><th>Rule</th><th>Breach</th><th>Clear<'
                    "/th><th>Unable</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>",
                    *[_s("text", "p", c) for c in caps],
                    *(
                        [
                            _s(
                                "text",
                                "p",
                                "The most common reason for \u201cunable\u201d: "
                                f"{FACT_SAY.get(top_fact, top_fact)} "
                                f"({top_n} rulings).",
                            )
                        ]
                        if top_fact
                        else []
                    ),
                ]
            ),
        )
    )
    rp = d["replay"]
    out.append(
        _panel(
            "p11",
            "replay",
            "\n".join(
                [
                    _s("kicker", "p", "The same bytes, twice", cls="kicker"),
                    _s("head", "h2", "Every ruling rebuilds from its record, offline"),
                    _s("text", "p", f"The rulings file, {rp['lines']} lines:"),
                    _s("mono", "p", "sha256 " + rp["preds_sha"], cls="hash big"),
                    _s("text", "p", "Rebuilt from the records alone, network off, no footage:"),
                    _s("mono", "p", "sha256 " + rp["replay_sha"], cls="hash big"),
                    _s(
                        "decided",
                        "p",
                        "Byte-identical." if rp["same"] else "NOT identical.",
                        cls="decided",
                    ),
                ]
            ),
        )
    )
    out.append(
        _panel(
            "p12",
            "close",
            "\n".join(
                [
                    _s("kicker", "p", "faultline", cls="kicker"),
                    _s(
                        "head",
                        "h2",
                        "Rules in, rulings out, and an honest \u201cI can't tell\u201d",
                    ),
                    _s(
                        "text",
                        "p",
                        "A breach shows the number that decided it. A clear shows what was "
                        "measured. "
                        "An unable ruling names the one fact it lacks. And anyone can "
                        "rebuild every ruling to the same bytes.",
                    ),
                ]
            ),
        )
    )
    return out


CSS = """
:root{--bg:#f6f5f2;--panel:#fff;--ink:#1c1d1f;--muted:#62656b;--line:#e2e0db;--soft:#efede8;
--breach:#b4232c;--breach-bg:#fbe9ea;--clear:#2f6b4f;--clear-bg:#e7f2ec;--unable:#9a6200;--unable-b\
g:#fbf1dc;
--accent:#2c4f8c;color-scheme:light}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#141518;--panel:#1c1e22;--\
ink:#e9e8e4;
--muted:#9a9ca3;--line:#2d3036;--soft:#24262b;--breach:#f0727a;--breach-bg:#3a1d20;--clear:#7cc7a2;\
--clear-bg:#183027;
--unable:#e6b35a;--unable-bg:#352914;--accent:#8fb0ec;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#141518;--panel:#1c1e22;--ink:#e9e8e4;--muted:#9a9ca3;--line:#2d3036;\
--soft:#24262b;
--breach:#f0727a;--breach-bg:#3a1d20;--clear:#7cc7a2;--clear-bg:#183027;--unable:#e6b35a;--unable-b\
g:#352914;
--accent:#8fb0ec;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:17px/1.5 system-ui,-apple-system,"Segoe \
UI",Roboto,sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px 16px 64px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:28px 28px \
24px;margin:0 0 20px}
.kicker{margin:0 0 6px;color:var(--muted);font-size:14px;letter-spacing:.04em;text-transform:upperc\
ase}
h1{margin:0 0 10px;font-size:52px;letter-spacing:-.02em}
h2{margin:0 0 16px;font-size:28px;letter-spacing:-.01em}
.lede{font-size:21px}
.pack{margin:0;padding-left:22px}.pack li{margin:0 0 14px}.pack p{margin:4px 0}
.onvideo,.evidence{color:var(--muted)}
.evidence,.hash,.onvideo{font-family:ui-monospace,"Cascadia \
Mono",Consolas,monospace;font-size:14px;overflow-wrap:anywhere}
.hash.big{font-size:16px;color:var(--ink);background:var(--soft);padding:8px 10px;border-radius:8px}
.frames{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:0 0 \
12px}
figure{margin:0}figure img{width:100%;height:auto;display:block;border-radius:8px;border:1px solid \
var(--line)}
figcaption{font-size:13px;color:var(--muted);margin-top:4px}
.badge{display:inline-block;font-weight:700;font-size:18px;padding:6px \
14px;border-radius:999px;margin:0 0 12px}
.badge.breach{color:var(--breach);background:var(--breach-bg)}.badge.clear{color:var(--clear);backg\
round:var(--clear-bg)}
.badge.unable{color:var(--unable);background:var(--unable-bg)}
.three{display:grid;grid-template-columns:max-content 1fr;gap:6px 16px;align-items:center}.three \
p{margin:0 0 12px}
.label{margin:10px 0 2px;color:var(--muted);font-size:13px;text-transform:uppercase;letter-spacing:\
.04em}
.decided{margin:0 0 8px;font-size:22px;font-weight:600}
.note{margin:0 0 12px;padding:12px 16px;border-left:4px solid \
var(--accent);background:var(--soft);border-radius:0 8px 8px 0}
.counts{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;margin:0 0 12px}
.counts th,.counts td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
.counts td{width:110px;font-weight:600}.counts td.breach{color:var(--breach)}.counts \
td.clear{color:var(--clear)}
.counts td.unable{color:var(--unable)}
@media (max-width:600px){.panel{padding:18px 16px}h1{font-size:38px}h2{font-size:22px}.counts \
td{width:auto}}
"""


def render(d: dict) -> str:
    body = "\n".join(panels(d))
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>faultline walkthrough</title>\n<style>"
        + CSS
        + "</style>\n</head>\n<body>\n<main>\n"
        + body
        + "\n</main>\n</body>\n</html>\n"
    )


def build(smoke_dir: Path, shift_dir: Path, pack_dir: Path, out: Path) -> str:
    page = render(gather(smoke_dir, shift_dir, pack_dir))
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(page.encode("utf-8"))
    return hashlib.sha256(page.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- stills


class _Panels(HTMLParser):
    """Each panel's `data-s` elements in page order: (role, text, attrs)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.panels: dict[str, dict] = {}
        self.cur: str | None = None
        self.stack: list[list] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "section" and "panel" in (a.get("class") or ""):
            self.cur = a["id"]
            self.panels[self.cur] = {"name": a.get("data-name", self.cur), "items": []}
            return
        if self.cur is None or "data-s" not in a:
            return
        if tag == "img":
            self.panels[self.cur]["items"].append(("img", a.get("data-cap", ""), a))
            return
        if "data-text" in a:
            self.panels[self.cur]["items"].append((a["data-s"], a["data-text"], a))
            return
        self.stack.append([tag, a["data-s"], []])

    def handle_data(self, data):
        if self.stack:
            self.stack[-1][2].append(data)

    def handle_endtag(self, tag):
        if tag == "section":
            self.cur = None
            return
        if self.stack and self.stack[-1][0] == tag:
            t, role, parts = self.stack.pop()
            self.panels[self.cur]["items"].append((role, " ".join("".join(parts).split()), {}))


def page_panels(page: str) -> dict[str, dict]:
    p = _Panels()
    p.feed(page)
    return p.panels


SCRIPT_LINE = re.compile(r"^\s*(\d+)\.\s.*\(on screen: (p\d\d)\b[^)]*\)")


def script_lines(script: str) -> list[tuple[int, str]]:
    return [
        (int(m.group(1)), m.group(2))
        for m in (SCRIPT_LINE.match(x) for x in script.splitlines())
        if m
    ]


def still_name(n: int, pid: str, name: str) -> str:
    return f"{n:02d}-{pid}-{name}.png"


import os  # noqa: E402

WINFONTS = (
    os.path.join(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "", "Fonts") + "/"
)
FONTS = {
    "regular": [
        WINFONTS + "segoeui.ttf",
        WINFONTS + "arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    ],
    "bold": [
        WINFONTS + "segoeuib.ttf",
        WINFONTS + "arialbd.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    ],
    "mono": [
        WINFONTS + "consola.ttf",
        WINFONTS + "cour.ttf",
        "/System/Library/Fonts/Menlo.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    ],
}

W, H, MX = 1920, 1080, 110
INK, MUTED, SOFT = "0x1C1D1F", "0x62656B", "0xEFEDE8"
BADGE_COL = {
    "breach": ("0xB4232C", "0xFBE9EA"),
    "clear": ("0x2F6B4F", "0xE7F2EC"),
    "unable": ("0x9A6200", "0xFBF1DC"),
}
# role: (font, size, colour, line gap, width factor: average glyph width as a share of the size)
STYLE = {
    "kicker": ("regular", 30, MUTED, 1.35, 0.52),
    "head": ("bold", 60, INK, 1.2, 0.55),
    "text": ("regular", 36, INK, 1.35, 0.50),
    "text-b": ("bold", 36, INK, 1.3, 0.55),
    "mono": ("mono", 27, MUTED, 1.4, 0.55),
    "label": ("regular", 26, MUTED, 1.4, 0.52),
    "decided": ("bold", 44, INK, 1.25, 0.55),
    "note": ("regular", 36, INK, 1.4, 0.50),
    "row": ("regular", 36, INK, 1.55, 0.50),
}


def _font(kind: str) -> str:
    for f in FONTS[kind]:
        if Path(f).is_file():
            return f
    for f in FONTS["regular"]:
        if Path(f).is_file():
            return f
    raise DemoError("no font file found for the stills")


def _wrap(text: str, size: int, factor: float, width: int) -> list[str]:
    per = max(10, int(width / (size * factor)))
    lines, cur = [], ""
    for word in text.split():
        if cur and len(cur) + 1 + len(word) > per:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}" if cur else word
    if cur:
        lines.append(cur)
    return lines


def _layout(panel: dict) -> tuple[list[dict], list[dict]]:
    """Draw ops for one panel: images in a row under the heading, text below; long panels shrink
    their text.
    """
    items = panel["items"]
    imgs = [a for role, _, a in items if role == "img"]
    for scale in (1.0, 0.9, 0.8, 0.7, 0.62, 0.55, 0.5):
        ops, places, y = [], [], 90
        img_done = False
        for role, text, _a in items:
            if role == "img":
                if img_done:
                    continue
                img_done = True
                n = len(imgs)
                gap = 18
                iw = min(
                    int(560 * (1 if n > 2 else 1.25) * scale) if n > 1 else int(900 * scale),
                    (W - 2 * MX - gap * (n - 1)) // n,
                )
                ih = iw * 9 // 16
                for k, im in enumerate(imgs):
                    x = MX + k * (iw + gap)
                    places.append({"src": im["src"], "x": x, "y": y, "w": iw, "h": ih})
                    ops.append(
                        {
                            "t": "text",
                            "s": im.get("data-cap", ""),
                            "font": "regular",
                            "size": int(24 * scale) + 2,
                            "col": MUTED,
                            "x": x,
                            "y": y + ih + 8,
                        }
                    )
                y += ih + 8 + int(40 * scale)
                continue
            if role.startswith("badge-"):
                v = role[len("badge-") :]
                fg, bg = BADGE_COL[v]
                size = int(44 * scale)
                bw = int(len(text) * size * 0.5) + 60
                ops.append({"t": "box", "x": MX, "y": y, "w": bw, "h": size + 30, "col": bg})
                ops.append(
                    {
                        "t": "text",
                        "s": text,
                        "font": "bold",
                        "size": size,
                        "col": fg,
                        "x": MX + 30,
                        "y": y + 13,
                    }
                )
                y += size + 30 + int(22 * scale)
                continue
            font, size, col, gapf, factor = STYLE.get(role, STYLE["text"])
            size = max(16, int(size * scale)) if role not in ("kicker",) else size
            x0, width = MX, W - 2 * MX
            if role == "note":
                ops.append(
                    {
                        "t": "box",
                        "x": MX,
                        "y": y - 10,
                        "w": 8,
                        "h": 0,
                        "col": "0x2C4F8C",
                        "grow": True,
                    }
                )
                x0, width = MX + 30, W - 2 * MX - 30
            lines = _wrap(text, size, factor, width)
            start = y
            for ln in lines:
                ops.append(
                    {"t": "text", "s": ln, "font": font, "size": size, "col": col, "x": x0, "y": y}
                )
                y += int(size * gapf)
            if role == "note":
                for o in ops:
                    if o.get("grow") and o["h"] == 0:
                        o["h"] = y - start + 10
            y += int(size * 0.45)
        if y <= H - 60:
            return ops, places
    return ops, places


def render_still(panel: dict, out: Path) -> None:
    ops, places = _layout(panel)
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        for k, f in (("r", "regular"), ("b", "bold"), ("m", "mono")):
            shutil.copyfile(_font(f), tdp / f"{k}.ttf")
        cmd = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=0xF6F5F2:s={W}x{H}:d=1",
        ]
        for i, pl in enumerate(places):
            raw = base64.b64decode(pl["src"].split(",", 1)[1])
            (tdp / f"i{i}.jpg").write_bytes(raw)
            cmd += ["-i", f"i{i}.jpg"]
        chain, last = [], "0:v"
        for i, pl in enumerate(places):
            chain.append(f"[{i + 1}:v]scale={pl['w']}:{pl['h']}[s{i}]")
            chain.append(f"[{last}][s{i}]overlay={pl['x']}:{pl['y']}[o{i}]")
            last = f"o{i}"
        draws = []
        fk = {"regular": "r", "bold": "b", "mono": "m"}
        for j, o in enumerate(ops):
            if o["t"] == "box":
                draws.append(
                    f"drawbox=x={o['x']}:y={o['y']}:w={o['w']}:h={max(o['h'], 1)}:color="
                    f"{o['col']}:t=fill"
                )
            else:
                (tdp / f"t{j}.txt").write_text(o["s"], encoding="utf-8")
                draws.append(
                    f"drawtext=fontfile={fk[o['font']]}.ttf:textfile=t{j}.txt:expansion=none"
                    f":x={o['x']}:y={o['y']}:"
                    f"fontsize={o['size']}:fontcolor={o['col']}"
                )
        tail = f"[{last}]" + (",".join(draws) if draws else "null") + "[out]"
        chain.append(tail)
        (tdp / "graph.txt").write_text(";\n".join(chain), encoding="utf-8")
        cmd += [
            "-filter_complex_script",
            "graph.txt",
            "-map",
            "[out]",
            "-frames:v",
            "1",
            "-c:v",
            "png",
            "out.png",
        ]
        try:
            subprocess.run(cmd, cwd=td, check=True, capture_output=True, timeout=300)
        except subprocess.CalledProcessError as e:
            raise DemoError(
                "ffmpeg could not draw a still: " + e.stderr.decode("utf-8", "replace")[-600:]
            ) from e
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(tdp / "out.png", out)


def stills(script_path: Path, page_path: Path, out_dir: Path) -> list[str]:
    page = Path(page_path).read_text(encoding="utf-8")
    pp = page_panels(page)
    lines = script_lines(Path(script_path).read_text(encoding="utf-8"))
    if not lines:
        raise DemoError("no script line names a panel as '(on screen: pNN)'")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*.png"):
        old.unlink()
    names = []
    for n, pid in lines:
        if pid not in pp:
            raise DemoError(f"script line {n} names {pid}, which the page does not have")
        name = still_name(n, pid, pp[pid]["name"])
        render_still(pp[pid], out_dir / name)
        names.append(name)
    return names


# ---------------------------------------------------------------- cli


def cmd(args) -> int:
    try:
        if args.stills:
            if not args.page:
                raise DemoError("--stills needs --page <page.html>")
            names = stills(Path(args.stills), Path(args.page), Path(args.out))
            print(f"{len(names)} stills to {args.out}")
            for n in names:
                print("  " + n)
            return 0
        if not (args.smoke and args.shift and args.rules):
            raise DemoError("the page needs --smoke, --shift and --rules")
        sha = build(Path(args.smoke), Path(args.shift), Path(args.rules), Path(args.out))
        print(f"page {args.out} sha256 {sha}")
        return 0
    except DemoError as e:
        print(f"faultline demo: {e}")
        return 2


__all__ = [
    "build",
    "gather",
    "render",
    "stills",
    "page_panels",
    "script_lines",
    "still_name",
    "cmd",
    "PICKS",
]
