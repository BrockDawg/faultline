"""The shift dashboard: one static HTML file, no server, no CDN, opens from disk.

It shows every window on the shift's clock with its rulings and the frames each ruling names, and
lets a reader act as the insurer (confirm, deny, close as final) or the site (dispute a confirmed
ruling). Moves follow the lifecycle table embedded from lifecycle.py; an illegal move is refused on
the page as it is in the CLI. The lifecycle is kept in the browser while the page is open and saved
as lifecycle.json beside the page. The page shows rulings, never a score.
The output is a pure function of its inputs, so a replay writes the same bytes.

Every unable ruling shows the fact it lacks, in the pack's own words where the pack has them (quoted
from the rule's text, site values unbracketed), and in plain words otherwise, beside the frames it
names. Every breach shows the rule, its frames and the measured number that decided it, quoted from
the script's own evidence. A model's verdict is never shown as the ruling: Wonder's words
(`--words`) appear only when the side file `preds.words.jsonl` sits beside the shift, in their own
panel marked as words beside the ruling. Without that file the page carries no words code at all.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from faultline.adapters.video import lifecycle
from faultline.adapters.video.shift import TITLES, ruling_frames

# the fact a ruling lacks, in plain words (used where the pack's own text does not name it)
FACT_WORDS = {
    "camera.static": "a camera held still over a marked floor plane",
    "window.one_shot": "one unbroken shot through the window",
    "window.covers_second": "at least one full second of footage",
    "truck.moving": "whether the truck was moving",
    "truck.speed_mps": "the truck's floor speed, clear of the limit either way",
    "truck.reversing": "whether the truck reversed for a second or more",
    "truck.direction": "which end of the truck it travelled towards",
    "truck.front_in_strip": "whether the truck came within the strip of a structure base",
    "person.on_foot": "whether the person was on foot",
    "person.vested": "whether the person wore a hi-vis band",
    "person.distance_m": "the person's distance from the moving truck, clear of the line either "
    "way",
    "person.in_rear_cone": "whether anyone stood in the rear cone",
    "person.still": "whether the person stood still",
    "person.in_dock_zone": "whether the person stood in a marked dock zone",
    "contact.consequence": "touch not provable from this camera; no consequence seen",
    "clip": "the clip itself",
    "route:out": "a rule this camera can judge",
    "route:unmapped": "a predicate over the measured fields",
}

# where the pack's own words name a fact: patterns over a rule's text (site values unbracketed),
# tried on the ruling's
# rule first, then the rest of the pack; CL runs to the end of a clause, past a decimal point
CL = r"(?:[^;.]|\.(?=\d))*"
PACK_ANCHORS = {
    "contact.consequence": [
        r"a consequence follows within [^)]*\)",
        r"A consequence within half a second \([^)]*\) is the evidence that the touch was real",
    ],
    "truck.front_in_strip": [
        r"[Tt]he truck's front comes within " + CL + r" in a row",
        r"with no structure base marked for the camera" + CL,
        r"[Tt]he truck or its load meets " + CL,
    ],
    "truck.moving": [
        r"Moving means over " + CL,
        r"A moving truck keeps at least " + CL,
    ],  # Public anchor
    "truck.speed_mps": [r"An interval that straddles the limit is not proven either way"],
    "person.distance_m": [
        r"A distance whose interval straddles the line is not proven either way",
        r"A person's feet come within the site distance" + CL,
    ],  #
    "truck.reversing": [
        r"[Tt]he truck travels against its fork end at over " + CL + r" or more",
        r"[Tt]he truck travels against its fork end " + CL + r" or more",
    ],
    "truck.direction": [r"Which end is the fork end must be known" + CL],
    "person.in_rear_cone": [r"inside the rear cone \([^)]*\)", r"no vested person behind it"],
    "person.vested": [
        r"(?:no|a) fluorescent " + CL + r" can be read",
        r"A person too small to read" + CL,
        r"A person who is too small to read" + CL,
    ],
    "person.in_dock_zone": [r"inside a marked dock zone" + CL],
    "person.still": [r"standing still" + CL],
}

# the measured number that decided a breach, quoted from the script's evidence (rules.py writes it
# from fixed forms)
DECIDED = {
    "site_speed_limit": [
        r"Peak floor speed [\d.]+ m/s \(interval [\d.]+ to [\d.]+\)",
        r"site limit of [\d.]+ m/s",
    ],
    "pedestrian_separation": [
        r"came within [\d.]+ m \(interval [\d.]+ to [\d.]+\)",
        r"site line is [\d.]+ m",
    ],
    "hi_vis_in_truck_zone": [
        r"no hi-vis band on the torso on \d+% of \d+ read frames",
        r"site line is \d+%",
    ],
    "spotter_when_reversing": [
        r"travelled against its fork end for [\d.]+ s",
        r"with (?:nobody on foot in frame|no vested person in the rear cone)",
    ],
    "structure_contact": [
        r"held within [\d.]+ m of the \S+ base from frame \d+ to \d+",
        r"consequence followed at frame \d+ \([^)]*\) within [\d.]+ s",
        r"\d+% of the ensemble",
    ],
}
NUMBER = re.compile(r"[^.;]*\d[^.;]*")


def _unbracket(s: str) -> str:
    return re.sub(r"\[([^\]]*)\]", r"\1", " ".join(s.split()))


def pack_words(fact: str | None, rule_id: str, pack_rules: list[dict]) -> str | None:
    """The pack's own sentence for the fact a ruling lacks, or None where no rule's text names
    it.
    """
    if not fact:
        return None
    texts = [r.get("text", "") for r in pack_rules if r["id"] == rule_id] + [
        r.get("text", "") for r in pack_rules if r["id"] != rule_id
    ]
    for pat in PACK_ANCHORS.get(fact, []):
        for t in texts:
            m = re.search(pat, _unbracket(t))
            if m:
                return m.group(0).strip()
    return None


def lacks(fact: str | None, rule_id: str, pack_rules: list[dict]) -> dict | None:
    if not fact:
        return None
    return {
        "field": fact,
        "words": FACT_WORDS.get(fact, fact),
        "pack": pack_words(fact, rule_id, pack_rules),
    }


def decided_by(rule_id: str, evidence: str) -> str:
    """The measured numbers that decided a breach, quoted from its evidence; the first numbered
    clause if no form matches.
    """
    got = [m.group(0) for pat in DECIDED.get(rule_id, []) for m in [re.search(pat, evidence)] if m]
    if got:
        return " · ".join(got)
    m = NUMBER.search(evidence)
    return m.group(0).strip() if m else evidence


def _payload(m, windows, preds, pack_rules, posters, rframes, init, key) -> dict:
    by = {p["id"]: p for p in preds}
    titles = {r["id"]: TITLES.get(r["id"], r["title"]) for r in pack_rules}
    out = []
    for w in windows:
        p = by[w["window"]]
        stem = Path(w["clip"]).stem
        k = (key or {}).get(stem)
        rl = []
        for r in p["rulings"]:
            fr = ruling_frames(r)
            rl.append(
                {
                    "rule": r["rule"],
                    "title": titles.get(r["rule"], r["rule"]),
                    "verdict": r["verdict"],
                    "missing_fact": r["missing_fact"],
                    "evidence": r["evidence"],
                    "lacks": lacks(r["missing_fact"], r["rule"], pack_rules)
                    if r["verdict"] == "unable_to_rule"
                    else None,
                    "decided": decided_by(r["rule"], r["evidence"])
                    if r["verdict"] == "breach"
                    else None,
                    "frames": [
                        {"i": i, "src": rframes[w["window"]].get(i)}
                        for i in fr
                        if rframes[w["window"]].get(i)
                    ],
                }
            )
        out.append(
            {
                "window": w["window"],
                "clip": stem,
                "shift_start_s": w["shift_start_s"],
                "shift_end_s": w["shift_end_s"],
                "gap_before_s": w["gap_before_s"],
                "poster": posters.get(w["window"]),
                "entry": p["entry"],
                "record": p["record"],
                "reviewed": None if k is None else {"label": k["label"], "rule": k.get("rule")},
                "rulings": rl,
            }
        )
    return {
        "name": m["name"],
        "note": m.get("note", ""),
        "windows": out,
        "states": list(lifecycle.STATES),
        "transitions": lifecycle.TRANSITIONS,
        "initial": init,
        "has_key": key is not None,
        "storage_key": "faultline-shift:" + m["name"] + ":" + init_hash(init),
    }


def init_hash(init: dict) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(init, sort_keys=True).encode()).hexdigest()[:12]


def words_payload(words: list[dict], preds: list[dict]) -> dict:
    """The words panel's data: each ruling's note and (where shipped) the model's read, keyed by
    window and rule.

    A words line whose verdict no longer matches the canonical ruling is dropped for that ruling, so
    a note is never shown beside a ruling it was not written for."""
    canon = {(p["id"], r["rule"]): r["verdict"] for p in preds for r in p["rulings"]}
    out: dict = {}
    for line in words:
        for r in line.get("rulings", []):
            if canon.get((line["id"], r["rule"])) != r.get("verdict"):
                continue
            if not r.get("note") and not r.get("model_read"):
                continue
            out.setdefault(line["id"], {})[r["rule"]] = {
                "note": r.get("note"),
                "model_read": r.get("model_read"),
            }
    return {"windows": out, "records": {line["id"]: line.get("record") for line in words}}


def _json_script(o) -> str:
    return json.dumps(o, ensure_ascii=False, sort_keys=True).replace("</", "<\\/")


def render(
    m, windows, preds, pack_rules, posters, rframes, init, key, words: list[dict] | None = None
) -> str:
    """The page. `words` is the side file's lines; None (no side file) leaves every words token
    empty, so the page carries no words data, style or code at all."""
    data = _json_script(_payload(m, windows, preds, pack_rules, posters, rframes, init, key))
    title = f"Shift {m['name']}"
    page = PAGE.replace("__TITLE__", _esc(title)).replace("__DATA__", data)
    if words is None:
        for tok in WORDS_TOKENS:
            page = page.replace(tok, "")
        return page
    wd = _json_script(words_payload(words, preds))
    return (
        page.replace("__WORDS_CSS__", WORDS_CSS)
        .replace("__WORDS_DATA__", WORDS_DATA.replace("__WD__", wd))
        .replace("__WORDS_FN__", WORDS_FN)
        .replace("__WORDS_RULING__", WORDS_RULING)
        .replace("__WORDS_INIT__", WORDS_INIT)
    )


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root{
  --bg:#f6f5f2; --panel:#ffffff; --ink:#1c1d1f; --muted:#62656b; --line:#e2e0db; --soft:#efede8;
  --breach:#b4232c; --breach-bg:#fbe9ea; --clear:#2f6b4f; --clear-bg:#e7f2ec; --unable:#9a6200; \
--unable-bg:#fbf1dc;
  --accent:#2c4f8c; --accent-bg:#e6edf8; --final:#3b3d42; --shadow:0 1px 2px rgba(0,0,0,.05),0 4px \
14px rgba(0,0,0,.05);
  color-scheme: light;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#141518; --panel:#1c1e22; --ink:#e9e8e4; --muted:#9a9ca3; --line:#2d3036; --soft:#24262b;
    --breach:#f0727a; --breach-bg:#3a1d20; --clear:#7cc7a2; --clear-bg:#183027; --unable:#e6b35a; \
--unable-bg:#352914;
    --accent:#8fb0ec; --accent-bg:#1e2a40; --final:#c9cbd1; --shadow:none; color-scheme: dark;
  }
}
:root[data-theme="dark"]{
  --bg:#141518; --panel:#1c1e22; --ink:#e9e8e4; --muted:#9a9ca3; --line:#2d3036; --soft:#24262b;
  --breach:#f0727a; --breach-bg:#3a1d20; --clear:#7cc7a2; --clear-bg:#183027; --unable:#e6b35a; \
--unable-bg:#352914;
  --accent:#8fb0ec; --accent-bg:#1e2a40; --final:#c9cbd1; --shadow:none; color-scheme: dark;
}
*{box-sizing:border-box}
html,body{margin:0}
body{background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe \
UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 64px}
header.top{position:sticky;top:0;z-index:5;background:color-mix(in srgb,var(--bg) \
92%,transparent);backdrop-filter:blur(8px);border-bottom:1px solid var(--line)}
.bar{max-width:1180px;margin:0 auto;padding:12px 16px;display:flex;flex-wrap:wrap;gap:10px \
18px;align-items:center}
h1{font-size:18px;margin:0;font-weight:650;letter-spacing:-.01em}
.sub{color:var(--muted);font-size:13px}
.grow{flex:1}
.seg{display:inline-flex;border:1px solid \
var(--line);border-radius:8px;overflow:hidden;background:var(--panel)}
.seg button{border:0;background:transparent;color:var(--muted);padding:6px \
12px;font:inherit;font-size:13px;cursor:pointer}
.seg button+button{border-left:1px solid var(--line)}
.seg button[aria-pressed="true"]{background:var(--accent-bg);color:var(--accent);font-weight:600}
.btn{border:1px solid var(--line);background:var(--panel);color:var(--ink);border-radius:8px;paddin\
g:6px 12px;font:inherit;font-size:13px;cursor:pointer}
.btn:hover{border-color:var(--muted)}
.btn:disabled{opacity:.45;cursor:not-allowed}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--panel)}
.timeline{display:flex;gap:2px;height:30px;margin:18px 0 6px;border-radius:6px;overflow:hidden}
.timeline a{display:block;flex:1 1 0;min-width:3px;background:var(--soft);position:relative}
.timeline a.v-breach{background:var(--breach)} .timeline a.v-unable{background:var(--unable)} \
.timeline a.v-clear{background:var(--clear)}
.timeline .gap{display:block;flex:1 1 0;background:repeating-linear-gradient(90deg,var(--line) 0 \
2px,transparent 2px 6px);opacity:.7}
.timeline a:hover{outline:2px solid var(--ink);outline-offset:-2px}
.tl-axis{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;font-variant-\
numeric:tabular-nums}
.legend{display:flex;flex-wrap:wrap;gap:14px;color:var(--muted);font-size:12px;margin:8px 0 18px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-a\
lign:-1px}
.filters{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:4px 0 18px}
.filters .lab{color:var(--muted);font-size:13px;margin-right:2px}
.chip{border:1px solid var(--line);background:var(--panel);color:var(--muted);border-radius:999px;p\
adding:4px 11px;font:inherit;font-size:13px;cursor:pointer}
.chip[aria-pressed="true"]{border-color:var(--ink);color:var(--ink);font-weight:600}
.card{background:var(--panel);border:1px solid \
var(--line);border-radius:12px;box-shadow:var(--shadow);margin:0 0 \
16px;overflow:hidden;scroll-margin-top:80px}
.card.flash{outline:2px solid var(--accent)}
.ch{display:grid;grid-template-columns:200px 1fr;gap:16px;padding:14px;border-bottom:1px solid \
var(--line)}
.ch img,.ch .noimg{width:200px;aspect-ratio:16/9;object-fit:cover;border-radius:8px;background:var(\
--soft);display:block}
.ch h2{font-size:15px;margin:0 0 2px;font-weight:650;word-break:break-word}
.meta{color:var(--muted);font-size:13px;font-variant-numeric:tabular-nums}
.tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.tag{font-size:12px;border-radius:6px;padding:2px 8px;background:var(--soft);color:var(--muted)}
.tag.rev{background:var(--accent-bg);color:var(--accent)}
.rl{padding:12px 14px;display:grid;grid-template-columns:200px 1fr;gap:6px 16px;border-top:1px \
solid var(--line)}
.rl:first-of-type{border-top:0}
.rl .rn{font-weight:600;font-size:14px}
.pill{display:inline-block;font-size:12px;font-weight:650;border-radius:6px;padding:1px \
8px;margin-top:4px}
.pill.breach{background:var(--breach-bg);color:var(--breach)} \
.pill.clear{background:var(--clear-bg);color:var(--clear)} \
.pill.unable_to_rule{background:var(--unable-bg);color:var(--unable)}
.mf{font-size:12px;color:var(--unable);margin-top:4px;font-family:ui-monospace,SFMono-Regular,Conso\
las,monospace}
.lk{border-left:3px solid var(--unable);background:var(--unable-bg);border-radius:0 8px 8px \
0;padding:8px 10px;margin-bottom:8px}
.lk-h{font-weight:600;font-size:14px;color:var(--ink)}
.lk-p{font-size:13px;color:var(--ink);margin-top:2px}
.lk .mf{margin-top:2px}
.dec{border-left:3px solid var(--breach);background:var(--breach-bg);border-radius:0 8px 8px \
0;padding:8px 10px;margin-bottom:8px;font-size:14px;font-variant-numeric:tabular-nums}
.dec-h{font-weight:600}
.nofr{margin-top:8px}
__WORDS_CSS__.ev{font-size:14px;color:var(--ink)}
.thumbs{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.thumbs button{border:0;padding:0;background:none;cursor:zoom-in;position:relative}
.thumbs img{width:150px;aspect-ratio:16/9;object-fit:cover;border-radius:6px;display:block;border:1\
px solid var(--line)}
.thumbs span{position:absolute;left:4px;bottom:4px;background:rgba(0,0,0,.65);color:#fff;font-size:\
11px;padding:0 5px;border-radius:4px;font-variant-numeric:tabular-nums}
.lc{margin-top:10px;padding:10px;border-radius:8px;background:var(--soft);display:flex;flex-wrap:wr\
ap;gap:8px;align-items:center}
.state{font-size:12px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;padding:2px \
8px;border-radius:6px;border:1px solid currentColor}
.state.identified{color:var(--accent)} .state.confirmed{color:var(--breach)} \
.state.denied{color:var(--clear)} .state.disputed{color:var(--unable)} \
.state.final{color:var(--final)}
.lc input{flex:1 1 160px;min-width:0;border:1px solid \
var(--line);background:var(--panel);color:var(--ink);border-radius:6px;padding:5px \
8px;font:inherit;font-size:13px}
.hist{width:100%;margin:2px 0 0;padding:0;list-style:none;font-size:12px;color:var(--muted)}
.hist li{padding:1px 0}
.empty{color:var(--muted);padding:30px;text-align:center}
.toast{position:fixed;left:50%;bottom:20px;transform:translateX(-50%);max-width:min(560px,calc(100v\
w - 32px));background:var(--ink);color:var(--bg);padding:10px \
14px;border-radius:8px;font-size:14px;opacity:0;transition:opacity \
.2s;pointer-events:none;z-index:20}
.toast.on{opacity:1}
.lb{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-conte\
nt:center;z-index:30;padding:16px;cursor:zoom-out}
.lb.on{display:flex}
.lb img{max-width:100%;max-height:90vh;border-radius:6px}
.lb p{position:absolute;bottom:14px;left:0;right:0;text-align:center;color:#eee;font-size:13px;marg\
in:0}
footer{color:var(--muted);font-size:12px;margin-top:28px}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px}
@media (max-width:720px){
  .ch,.rl{grid-template-columns:1fr}
  .ch img,.ch .noimg{width:100%}
  .thumbs img{width:calc(50vw - 40px)}
}
</style>
</head>
<body>
<header class="top"><div class="bar">
  <div><h1 id="title"></h1><div class="sub" id="sub"></div></div>
  <div class="grow"></div>
  <div class="seg" role="group" aria-label="Acting as"><button data-role="insurer" \
aria-pressed="true">Insurer</button><button data-role="site" \
aria-pressed="false">Site</button></div>
  <button class="btn primary" id="save">Save lifecycle.json</button>
  <label class="btn" for="load" tabindex="0">Load…</label><input type="file" id="load" \
accept=".json,application/json" hidden>
  <button class="btn" id="reset" title="Back to every ruling identified">Reset</button>
</div></header>
<main class="wrap">
  <nav class="timeline" id="timeline" aria-label="Shift timeline"></nav>
  <div class="tl-axis"><span>0:00</span><span id="tl-end"></span></div>
  <div class="legend"><span><i style="background:var(--breach)"></i>a breach ruling</span><span><i \
style="background:var(--unable)"></i>unable to rule on something, no breach</span><span><i \
style="background:var(--clear)"></i>every rule clear</span><span><i \
style="background:var(--line)"></i>time between clips</span></div>
  <div class="filters" id="filters"></div>
  <section id="list"></section>
  <footer id="foot"></footer>
</main>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<div class="lb" id="lb"><img alt=""><p></p></div>
<script type="application/json" id="data">__DATA__</script>
__WORDS_DATA__<script>
(function(){
"use strict";
var D = JSON.parse(document.getElementById("data").textContent);
var T = D.transitions;
var role = "insurer", vf = "all", sf = "all";
var LC = clone(D.initial);
__WORDS_FN__
function clone(o){ return JSON.parse(JSON.stringify(o)); }
function el(tag, attrs, kids){
  var e = document.createElement(tag);
  if (attrs) for (var k in attrs){ if (k === "text") e.textContent = attrs[k]; else if (k === \
"cls") e.className = attrs[k]; else e.setAttribute(k, attrs[k]); }
  (kids || []).forEach(function(c){ if (c) e.appendChild(c); });
  return e;
}
function mmss(s){ s = Math.round(s); var m = Math.floor(s / 60), r = s % 60; return m + ":" + (r < \
10 ? "0" : "") + r; }
function toast(msg){ var t = document.getElementById("toast"); t.textContent = msg; \
t.classList.add("on"); clearTimeout(toast.h); toast.h = setTimeout(function(){ \
t.classList.remove("on"); }, 3600); }

/* the lifecycle: the same table and the same refusals as lifecycle.py */
function check(state, to, by){
  if (!T.hasOwnProperty(state)) return "unknown state " + state;
  var allowed = T[state];
  if (!allowed.hasOwnProperty(to)){
    var nxt = Object.keys(allowed).map(function(k){ return k + " (by " + allowed[k] + ")"; \
}).join(", ") || "nothing; a final ruling never moves";
    return state + " → " + to + " is not an allowed move; from " + state + " the allowed moves \
are: " + nxt;
  }
  if (allowed[to] !== by) return state + " → " + to + " is made by the " + allowed[to] + ", not \
the " + by;
  return null;
}
function move(key, to, note){
  var r = LC.rulings[key];
  var why = check(r.state, to, role);
  if (why){ toast("Refused: " + why); return false; }
  r.history.push({from: r.state, to: to, by: role, note: note || "", at: new \
Date().toISOString().slice(0, 19) + "+00:00"});
  r.state = to; persist(); render(); toast(key + " is now " + to);
  return true;
}
/* a loaded file is accepted only if every ruling's history replays legally from identified */
function validate(doc){
  if (!doc || typeof doc.rulings !== "object") return "not a lifecycle file";
  for (var k in D.initial.rulings){ if (!doc.rulings[k]) return "missing ruling " + k; }
  for (var k2 in doc.rulings){
    if (!D.initial.rulings[k2]) return "ruling " + k2 + " is not in this shift";
    var r = doc.rulings[k2], st = "identified";
    for (var i = 0; i < (r.history || []).length; i++){
      var h = r.history[i];
      if (h.from !== st) return k2 + ": move " + (i + 1) + " starts from " + h.from + " but the \
ruling was " + st;
      var why = check(st, h.to, h.by); if (why) return k2 + ": move " + (i + 1) + ": " + why;
      st = h.to;
    }
    if (st !== r.state) return k2 + ": state " + r.state + " does not follow from its history";
  }
  return null;
}
function persist(){ try { localStorage.setItem(D.storage_key, JSON.stringify(LC)); } catch (e) {} }
function restore(){
  try { var s = localStorage.getItem(D.storage_key); if (s){ var d = JSON.parse(s); if \
(!validate(d)) LC = d; } } catch (e) {}
}

function windowClass(w){
  var v = w.rulings.map(function(r){ return r.verdict; });
  return v.indexOf("breach") >= 0 ? "breach" : v.indexOf("unable_to_rule") >= 0 ? "unable" : \
"clear";
}
function keyOf(w, r){ return w.window + "/" + r.rule; }
function windowStates(w){ return w.rulings.filter(function(r){ return LC.rulings[keyOf(w, r)]; \
}).map(function(r){ return LC.rulings[keyOf(w, r)].state; }); }
function shown(w){
  if (vf !== "all" && windowClass(w) !== vf) return false;
  if (sf !== "all" && windowStates(w).indexOf(sf) < 0) return false;
  return true;
}

function header(){
  var n = D.windows.length, end = n ? D.windows[n - 1].shift_end_s : 0;
  document.getElementById("title").textContent = "Shift " + D.name;
  document.getElementById("sub").textContent = n + " windows · every window ruled or named unable \
· " + mmss(end) + " of footage";
  document.getElementById("tl-end").textContent = mmss(end);
  var tl = document.getElementById("timeline");
  D.windows.forEach(function(w){
    if (w.gap_before_s > 0){ var g = el("span", {cls: "gap", title: w.gap_before_s + " s between \
clips"}); g.style.flexGrow = w.gap_before_s; tl.appendChild(g); }
    var a = el("a", {href: "#" + w.window, cls: "v-" + windowClass(w), title: w.window + "  " + \
mmss(w.shift_start_s) + "–" + mmss(w.shift_end_s)});
    a.style.flexGrow = Math.max(0.1, w.shift_end_s - w.shift_start_s);
    a.addEventListener("click", function(ev){ ev.preventDefault(); jump(w.window); });
    tl.appendChild(a);
  });
  var f = document.getElementById("filters");
  f.appendChild(el("span", {cls: "lab", text: "Windows"}));
  [["all","All"],["breach","With a breach"],["unable","Unable to rule"],["clear","All \
clear"]].forEach(function(p){
    var b = el("button", {cls: "chip", "aria-pressed": String(p[0] === vf), "data-v": p[0], text: \
p[1]});
    b.addEventListener("click", function(){ vf = p[0]; sf = "all"; syncChips(); render(); });
    f.appendChild(b);
  });
  f.appendChild(el("span", {cls: "lab", text: " Lifecycle"}));
  D.states.forEach(function(s){
    var b = el("button", {cls: "chip", "aria-pressed": "false", "data-s": s, text: s});
    b.addEventListener("click", function(){ sf = sf === s ? "all" : s; vf = "all"; syncChips(); \
render(); });
    f.appendChild(b);
  });
  document.getElementById("foot").innerHTML = "";
  document.getElementById("foot").appendChild(document.createTextNode(
    "Rulings are made by script from measured facts; a fact that was not measured makes the ruling \
“unable to rule” and names it. " +
    "The insurer confirms or denies a breach ruling, the site may dispute a confirmed one, and the \
insurer closes it as final. " +
    "Moves are kept in this browser while the page is open; Save writes lifecycle.json to keep \
beside this page."));
}
function syncChips(){
  document.querySelectorAll(".chip[data-v]").forEach(function(b){ b.setAttribute("aria-pressed", \
String(b.getAttribute("data-v") === vf)); });
  document.querySelectorAll(".chip[data-s]").forEach(function(b){ b.setAttribute("aria-pressed", \
String(b.getAttribute("data-s") === sf)); });
}
function jump(id){
  vf = "all"; sf = "all"; syncChips(); render();
  var c = document.getElementById(id); if (!c) return;
  c.scrollIntoView({behavior: "smooth", block: "start"});
  c.classList.add("flash"); setTimeout(function(){ c.classList.remove("flash"); }, 1400);
}
function lightbox(src, cap){
  var lb = document.getElementById("lb"); lb.querySelector("img").src = src; \
lb.querySelector("p").textContent = cap; lb.classList.add("on");
}

function lifecycleBox(w, r){
  var key = keyOf(w, r), st = LC.rulings[key];
  var box = el("div", {cls: "lc"});
  box.appendChild(el("span", {cls: "state " + st.state, text: st.state}));
  var note = el("input", {type: "text", placeholder: role === "insurer" ? "Note (optional)" : \
"Reason for the dispute (optional)", "aria-label": "Note"});
  var moves = [["confirmed","Confirm"],["denied","Deny"],["disputed","Dispute"],["final","Close as \
final"]];
  var any = false;
  moves.forEach(function(mv){
    var why = check(st.state, mv[0], role);
    var legalForSomeone = T[st.state] && T[st.state].hasOwnProperty(mv[0]);
    if (!legalForSomeone) return;
    any = true;
    var b = el("button", {cls: "btn", text: mv[1], title: why || ""});
    if (why) b.disabled = true;
    b.addEventListener("click", function(){ move(key, mv[0], note.value); });
    box.appendChild(b);
  });
  if (any) box.appendChild(note);
  else box.appendChild(el("span", {cls: "meta", text: "Closed. A final ruling never moves."}));
  if (st.history.length){
    var ul = el("ul", {cls: "hist"});
    st.history.forEach(function(h){ ul.appendChild(el("li", {text: h.from + " → " + h.to + " by \
the " + h.by + (h.note ? ": “" + h.note + "”" : "") + (h.at ? "  · " + h.at.replace("T", " \
").slice(0, 16) : "")})); });
    box.appendChild(ul);
  }
  return box;
}

function card(w){
  var c = el("article", {cls: "card", id: w.window});
  var img = w.poster ? el("img", {src: w.poster, alt: "Frame from " + w.clip, loading: "lazy"}) : \
el("div", {cls: "noimg"});
  var tags = el("div", {cls: "tags"}, [
    el("span", {cls: "tag", text: "entry " + w.entry}),
    el("span", {cls: "tag", text: "record " + w.record.slice(0, 12)})
  ]);
  if (w.reviewed) tags.appendChild(el("span", {cls: "tag rev", text: "reviewed: " + \
w.reviewed.label + (w.reviewed.rule ? " · " + w.reviewed.rule.replace(/_/g, " ") : "")}));
  c.appendChild(el("div", {cls: "ch"}, [img, el("div", null, [
    el("h2", {text: w.window}),
    el("div", {cls: "meta", text: "shift " + mmss(w.shift_start_s) + "–" + mmss(w.shift_end_s) + " \
· clip " + w.clip + (w.gap_before_s ? " · " + w.gap_before_s + " s gap before" : "")}),
    tags
  ])]));
  w.rulings.forEach(function(r){
    var left = el("div", null, [el("div", {cls: "rn", text: r.title}), el("span", {cls: "pill " + \
r.verdict, text: r.verdict === "unable_to_rule" ? "unable to rule" : r.verdict})]);
    var right = el("div");
    if (r.lacks){
      var lk = el("div", {cls: "lk"}, [el("div", {cls: "lk-h", text: "Lacks: " + r.lacks.words})]);
      if (r.lacks.pack) lk.appendChild(el("div", {cls: "lk-p", text: "The pack: “" + r.lacks.pack \
+ "”"}));
      lk.appendChild(el("div", {cls: "mf", text: "fact " + r.lacks.field}));
      right.appendChild(lk);
    }
    if (r.decided) right.appendChild(el("div", {cls: "dec"}, [el("span", {cls: "dec-h", text: \
"Decided by the measurement: "}), document.createTextNode(r.decided)]));
    right.appendChild(el("div", {cls: "ev", text: r.evidence}));
    if (r.frames.length){
      var th = el("div", {cls: "thumbs"});
      r.frames.forEach(function(f){
        var b = el("button", {type: "button", "aria-label": "Frame " + f.i}, [el("img", {src: \
f.src, alt: "Frame " + f.i, loading: "lazy"}), el("span", {text: "frame " + f.i})]);
        b.addEventListener("click", function(){ lightbox(f.src, w.window + " · " + r.title + " · \
frame " + f.i); });
        th.appendChild(b);
      });
      right.appendChild(th);
    } else if (r.verdict !== "clear") right.appendChild(el("div", {cls: "meta nofr", text: "This \
ruling names no frame; the window's own frame is at the top of the card."}));
    if (LC.rulings[keyOf(w, r)]) right.appendChild(lifecycleBox(w, r));__WORDS_RULING__
    c.appendChild(el("div", {cls: "rl"}, [left, right]));
  });
  return c;
}

function render(){
  var list = document.getElementById("list"), y = window.scrollY;
  list.innerHTML = "";
  var vis = D.windows.filter(shown);
  vis.forEach(function(w){ list.appendChild(card(w)); });
  if (!vis.length) list.appendChild(el("div", {cls: "empty", text: "No window matches this \
filter."}));
  window.scrollTo(0, y);
}

document.querySelectorAll(".seg button").forEach(function(b){
  b.addEventListener("click", function(){
    role = b.getAttribute("data-role");
    document.querySelectorAll(".seg button").forEach(function(x){ x.setAttribute("aria-pressed", \
String(x === b)); });
    render(); toast("Acting as the " + role);
  });
});
document.getElementById("save").addEventListener("click", function(){
  var text = JSON.stringify(LC, null, 1) + "\\n";
  if (window.showSaveFilePicker){
    window.showSaveFilePicker({suggestedName: "lifecycle.json", types: [{description: "Lifecycle", \
accept: {"application/json": [".json"]}}]})
      .then(function(h){ return h.createWritable().then(function(wr){ return \
wr.write(text).then(function(){ return wr.close(); }); }); })
      .then(function(){ toast("Saved lifecycle.json"); }, function(e){ if (e && e.name !== \
"AbortError") download(text); });
  } else download(text);
});
function download(text){
  var a = el("a", {href: URL.createObjectURL(new Blob([text], {type: "application/json"})), \
download: "lifecycle.json"});
  document.body.appendChild(a); a.click(); a.remove(); toast("Downloaded lifecycle.json; keep it \
beside this page");
}
document.getElementById("load").addEventListener("change", function(ev){
  var f = ev.target.files[0]; if (!f) return;
  f.text().then(function(t){
    var d; try { d = JSON.parse(t); } catch (e) { toast("Refused: not JSON"); return; }
    var why = validate(d);
    if (why){ toast("Refused: " + why); return; }
    LC = d; persist(); render(); toast("Loaded " + f.name);
  });
  ev.target.value = "";
});
document.getElementById("reset").addEventListener("click", function(){
  if (!confirm("Put every ruling back to identified?")) return;
  LC = clone(D.initial); persist(); render(); toast("Every ruling is identified again");
});
document.getElementById("lb").addEventListener("click", function(){ this.classList.remove("on"); });
document.addEventListener("keydown", function(e){ if (e.key === "Escape") \
document.getElementById("lb").classList.remove("on"); });

restore(); header();__WORDS_INIT__ render();
if (location.hash.length > 1){ var h0 = \
document.getElementById(decodeURIComponent(location.hash.slice(1))); if (h0) \
h0.scrollIntoView({block: "start"}); }
window.faultlineLifecycle = {check: check, validate: validate};
})();
</script>
</body>
</html>
"""


WORDS_TOKENS = (
    "__WORDS_CSS__",
    "__WORDS_DATA__",
    "__WORDS_FN__",
    "__WORDS_RULING__",
    "__WORDS_INIT__",
)

WORDS_CSS = """.words{margin-top:10px;border:1px dashed var(--line);border-radius:8px;padding:8px \
10px;background:var(--panel)}
.words-h{font-size:11px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--m\
uted)}
.words p{margin:4px 0 0;font-size:13px;color:var(--muted)}
.words p.wn{font-style:italic}
"""

WORDS_DATA = """<script type="application/json" id="words">__WD__</script>
"""

WORDS_FN = """var WD = JSON.parse(document.getElementById("words").textContent);
function wordsBox(w, r){
  var x = (WD.windows[w.window] || {})[r.rule];
  var label = r.verdict === "unable_to_rule" ? "unable to rule" : r.verdict;
  var box = el("aside", {cls: "words", "aria-label": "Words beside the ruling"}, [el("div", {cls: \
"words-h", text: "Words beside the ruling, not the ruling"})]);
  box.appendChild(el("p", {cls: x && x.note ? "wn" : "", text: x && x.note ? x.note : "No note is \
recorded for this ruling."}));
  if (x && x.model_read) box.appendChild(el("p", {text: "Three agreeing model reads of the frames \
said " + x.model_read + ". The ruling is the script's: " + label + "."}));
  return box;
}
"""

WORDS_RULING = """
    right.appendChild(wordsBox(w, r));"""

WORDS_INIT = """
document.getElementById("foot").appendChild(document.createTextNode(" The words panels are a \
model's notes written beside each ruling after the script made it; they never make or change a \
ruling."));"""
