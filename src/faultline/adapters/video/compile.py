"""The compiler: a markdown rules pack into predicates over the closed field vocabulary, with a
route per rule.

Two seats.

The script seat is the hand route key (`data/route_key.json`), fixed before any model run: for
every rule id in the eight packs it names the route (`window`: judged over a fixed-camera clip
window; `scan`: a contact scan over a broadcast recording; `out`: nothing in the vocabulary measures
it) and, for a window or scan rule, the predicates. A rule the key does not name falls to a keyword
grammar whose every condition carries the words it matched as its `span`.

The model seat is Spark Open. Rules go ten to a call, three runs per batch; each rule's three
proposals are kept in the record (`record/compile/rules/<id>.<text sha>.json`), so a later compile,
a scorer's included, reads them back with no call. A model predicate ships only when all three runs
agree on route and conditions, and only inside the vocabulary with every number spanned; every rule
reports its agreement count (0 to 3). The route key's route always stands: the model's agreed
proposal ships beside it, and a disagreement with the key is reported, never silently applied.

Every row is checked before it leaves: no field outside the vocabulary, no number without a `span`
(the rule's own words, found in its text) or a `site` key, and no `window` or `scan` route that
names no field (bait).

Thresholds: the route key writes no number into a predicate. Every threshold is a `line: {site,
span}` (`within` for a time window, `min` for a duration): the site.json key that holds the value
and the words of the rule it came from, so a site changes a value without touching the pack and no
literal sits bare.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from faultline.adapters.video import client
from faultline.adapters.video.rules import VOCAB

MODEL = "meta-models/muse-spark-open-1026"
RUNS = 3
BATCH = 10
MAX_TOKENS = 16000
# At 16,000 tokens; an earlier build ran "low" (the default effort spent all 12,000 tokens on 2 of 3
# runs, record/compile/ledger.jsonl) and its seat routed 105 of 110 rules out
EFFORT = "medium"
ASSETS = Path(__file__).resolve().parent / "data"
ROUTES = ("window", "scan", "out")
CONDS = (
    "is",
    "band",
    "count_vested",
    "min_s",
    "within_s",
    "default",
)  # the condition keys of the grammar
BANDS = ("under", "over", "high", "low")

# provenance by content: the words a rule uses for the quantity each site key holds, and the words
# for small
# numbers. A threshold's span must hold the site's number as written or one of these words; a
# literal's span its number.
# The same lists sit in scripts/check_spans.py, the checker written before this compiler was
# changed.
QUANTITY_WORDS = {
    "pedestrian_separation_m": ["metres", "metre", "distance"],
    "speed_limit_mps": ["speed limit", "metres per second", "m/s"],
    "moving_mps": ["moving", "moves", "travels"],
    "moving_window_s": ["second"],
    "stopped_window_s": ["stopped", "stops", "stationary"],
    "dock_guide_max_mps": ["dock"],
    "rear_cone_depth_truck_lengths": ["behind", "rear path", "rear"],
    "structure_run_frames": ["touch", "touches", "meets"],
    "consequence_window_s": ["half a second", "within"],
}
# "a " no longer names 1 (any sentence passed); tighter words do.
NUMBER_WORDS = {
    0: ["no ", "none", "zero", "nobody", "no one"],
    1: ["one", "a second", "a metre", "single"],
    2: ["two"],
    3: ["three"],
}
# Site values the pack text does not hold (the reader checked all five thresholds by value: the rear
# cone's 35 degrees,
# the 0.3 m structure strip and the 0.7 hi-vis share appear in no rule's words). Such a threshold is
# written
# {"site": k, "explicit": "<why>"} with no span: it says it comes from the site file, and the
# checker counts and lists it.
# Any other threshold with no span still fails, and a word span can no longer stand in for these
# three.
EXPLICIT_SITE = ("rear_cone_half_angle_deg", "structure_strip_m", "hivis_rule_share", "moving_mps")
# (Rulings 2 and 6): the moving line joins them. The three the rulings name (moving_mps,
# structure_strip_m, hivis_rule_share) are declared in data/site_values.json, which
# scripts/check_spans.py reads; the rear cone is allowed to ship in the explicit form but is not
# declared, so the checker still counts it weak.


def declared_site_values() -> dict[tuple[str, str], str]:
    """(Rule id, site key) -> why, from data/site_values.json."""
    p = ASSETS / "site_values.json"
    if not p.exists():
        return {}
    return {
        (e["rule"], e["site"]): e["why"]
        for e in json.loads(p.read_text(encoding="utf-8"))["values"]
    }


GATES = [
    {"field": "camera.static", "is": True},
    {"field": "window.one_shot", "is": True},
    {"field": "window.covers_second", "is": True},
]

# keyword grammar for rules the route key does not name; the matched words become the condition's
# span
GRAMMAR = [
    (r"revers\w*", "truck.reversing", {"is": True}),
    (r"high-?vis\w*|hi-?vis|vest\w*", "person.vested", {"is": False}),
    (
        r"metres? (?:between|from)|distance|separation|clearance",
        "person.distance_m",
        {"band": "under"},
    ),
    (r"speed|m/s|walking pace|too fast", "truck.speed_mps", {"band": "high"}),
    (r"touch\w*|contact|strike\w*|collid\w*|racking|upright", "truck.front_in_strip", {"is": True}),
    (r"touch\w*|contact|strike\w*|collid\w*", "contact.consequence", {"is": True}),
    (r"pedestrian|person on foot|people on foot|on foot", "person.on_foot", {"is": True}),
    (r"dock", "person.in_dock_zone", {"is": True}),
    (
        r"no (?:vested )?(?:person|spotter)[^.,;]*behind[^.,;]*",
        "person.in_rear_cone",
        {"count_vested": 0},
    ),
]
OUT_WORDS = re.compile(
    r"inspect|fuel|charg|battery|licen|train|certif|report|appeal|membership|schedule|attend"
    r"ance|chat|"
    r"communication|substitut|eligib|format|qualifying|points|playoff|protest|steward|anti-c"
    r"heat|aids|"
    r"rated capacity|nameplate|modif|out of service|horseplay|seat ?belt|limbs|riders",
    re.I,
)

# which measuring seat in rules.judge a compiled rule reads, by the fields its predicates name
KINDS = [
    ("hi_vis", {"person.vested"}),
    ("spotter", {"truck.reversing", "person.in_rear_cone"}),
    ("separation", {"person.distance_m"}),
    ("structure", {"truck.front_in_strip"}),
    ("speed", {"truck.speed_mps"}),
]


# -- the pack
# --------------------------------------------------------------------------------------------------


def parse_rule(text: str, path: Path | None = None) -> dict:
    m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n(.*)\Z", text, re.S)
    head, body = (m.group(1), m.group(2)) if m else ("", text)
    meta = {}
    for line in head.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip()
    rid = meta.get("id") or (path.stem.split("-", 1)[-1].replace("-", "_") if path else "rule")
    ov = re.search(r"On video:\s*(.+?)(?:\n\n|\n(?=Source:)|\Z)", body, re.S)
    return {
        "id": rid,
        "title": meta.get("title", rid),
        "text": body.strip(),
        "on_video": ov.group(1).strip() if ov else "",
        "file": path.name if path else None,
    }


def load_pack(folder: Path) -> dict:
    folder = Path(folder)
    meta = (
        json.loads((folder / "pack.json").read_text(encoding="utf-8"))
        if (folder / "pack.json").exists()
        else {}
    )
    rules = [
        parse_rule(p.read_text(encoding="utf-8"), p)
        for p in sorted(folder.glob("*.md"))
        if p.name.lower() != "readme.md"
    ]
    return {
        "name": meta.get("name", folder.name),
        "version": meta.get("version", ""),
        "domain": meta.get("domain", ""),
        "slug": folder.name,
        "rules": rules,
    }


def load_rules_dir(path: Path) -> list[dict]:
    """A pack folder, or a folder of pack folders, or a single pack.md file."""
    path = Path(path)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        parts = re.split(r"\n(?=---\s*\nid:)", "\n" + text)
        rules = [parse_rule(p.strip(), None) for p in parts if "id:" in p]
        return [{"name": path.stem, "version": "", "domain": "", "slug": path.stem, "rules": rules}]
    if list(path.glob("*.md")) and not any(
        d.is_dir() and (d / "pack.json").exists() for d in path.iterdir()
    ):
        return [load_pack(path)]
    return [load_pack(d) for d in sorted(path.iterdir()) if d.is_dir() and list(d.glob("*.md"))]


def _norm(s: str) -> str:
    return " ".join(s.replace("*", "").split()).lower()


def text_sha(rule: dict) -> str:
    return hashlib.sha256(_norm(rule["text"]).encode("utf-8")).hexdigest()


def route_key() -> dict:
    return json.loads((ASSETS / "route_key.json").read_text(encoding="utf-8"))["rules"]


def site_keys() -> set[str]:
    return set(json.loads((ASSETS / "site.json").read_text(encoding="utf-8")))


# -- the checks every row passes
# ---------------------------------------------------------------------------------------


def fields_of(predicates: list[dict]) -> list[str]:
    return [c["field"] for p in predicates for c in p.get("all", [])]


def _verbatim(s: str) -> str:
    """Case kept: a span must be the rule's own words; only markdown `*` and runs of whitespace are
    evened out.
    """
    return " ".join(str(s).replace("*", "").split())


def _names_number(span: str, v) -> bool:
    s = _verbatim(span)
    texts = [repr(v)] + ([str(int(v))] if isinstance(v, float) and v.is_integer() else [])
    if any(re.search(rf"(?<![\d.]){re.escape(t)}(?!\d)", s) for t in texts):
        return True
    return any(w in s.lower() + " " for w in NUMBER_WORDS.get(v, []))


def _site_values() -> dict:
    return json.loads((ASSETS / "site.json").read_text(encoding="utf-8"))


def problems(row: dict, rule: dict, sites) -> list[str]:
    """Why a compiled row may not ship: an invented field, a bare number, a weak span, a site-key
    fault, bait.

    Provenance by content: every span is a verbatim substring of the rule's own text (case kept); a
    threshold {site, span} names its quantity (the site's number as written, or a word from
    QUANTITY_WORDS); every number is the `value` of a dict with its own span that names it; a
    boolean site setting is a `switch`, never a threshold.
    `sites` is the site.json dict (a set of keys is accepted and read against data/site.json).
    """
    site = sites if isinstance(sites, dict) else _site_values()
    out = []
    text = _verbatim(rule.get("title", "") + " \n " + rule["text"])

    def walk(o):
        if isinstance(o, bool) or o is None or isinstance(o, str):
            return
        if isinstance(o, (int, float)):
            out.append(f"bare number {o}")
            return
        if isinstance(o, list):
            for v in o:
                walk(v)
            return
        if not isinstance(o, dict):
            return
        if "field" in o and o["field"] not in VOCAB:
            out.append(f"invented field {o['field']!r}")
        if "span" in o and o["span"] is not None and _verbatim(o["span"]) not in text:
            out.append(f"span not in the rule text: {o['span']!r}")
        if "switch" in o:
            sw = o["switch"]
            if not isinstance(sw, dict) or not isinstance(site.get(sw.get("site")), bool):
                out.append(f"switch is not a boolean site key: {sw!r}")
        if "policy" in o:
            # A `policy` naming a numeric site key is a threshold with no span by another name; it
            # fails
            k = o["policy"]
            if k not in site:
                out.append(f"site policy unknown: {k!r}")
            elif isinstance(site[k], (int, float)) and not isinstance(site[k], bool):
                out.append(
                    f"policy {k!r} names a numeric site key: a threshold must be a spanned "
                    "or explicit site value"
                )
        if "site" in o:
            k = o["site"]
            if k not in site:
                out.append(f"site key unknown: {k!r}")
            elif isinstance(site[k], bool):
                out.append(f"boolean site key {k!r} used as a threshold")
            elif o.get("explicit") and not o.get("span"):
                if k not in EXPLICIT_SITE:
                    out.append(
                        f"threshold {k} written as an explicit site value, but the pack "
                        "text names its quantity: it needs a span"
                    )
            elif not o.get("span"):
                out.append(f"threshold {k} has no span")
            elif not (
                (isinstance(site[k], (int, float)) and _names_number(o["span"], site[k]))
                or any(w in _verbatim(o["span"]).lower() for w in QUANTITY_WORDS.get(k, []))
            ):
                out.append(
                    f"threshold {k} spanned by {o['span']!r}, which does not name the quantity"
                )
        if isinstance(o.get("value"), (int, float)) and not isinstance(o.get("value"), bool):
            if not o.get("span"):
                out.append(f"value {o['value']} with no span of its own")
            elif not _names_number(o["span"], o["value"]):
                out.append(f"value {o['value']} spanned by {o['span']!r}, which does not name it")
        for k, v in o.items():
            if k == "switch" or (k == "value" and isinstance(v, (int, float))):
                continue
            walk(v)

    walk({k: row[k] for k in ("predicates", "unless", "gates") if k in row})
    if row.get("route") not in ROUTES:
        out.append(f"route {row.get('route')!r}")
    elif row["route"] != "out" and not fields_of(row.get("predicates", [])):
        out.append("bait: routed to video with no field named")
    return out


# -- the script seat
# --------------------------------------------------------------------------------------------------


def kind_of(predicates: list[dict]) -> str | None:
    have = set(fields_of(predicates))
    for kind, need in KINDS:
        if need <= have:
            return kind
    return None


def grammar_compile(rule: dict) -> dict:
    hay = (rule.get("on_video") or "") + " " + rule["title"]
    preds, seen = [], set()
    for pat, field, cond in GRAMMAR:
        m = re.search(pat, hay, re.I)
        if m and field not in seen:
            seen.add(field)
            if "count_vested" in cond:  # a number carries its own span
                cond = {"count_vested": {"value": cond["count_vested"], "span": m.group(0)}}
            preds.append({"field": field, **cond, "span": m.group(0)})
    if OUT_WORDS.search(rule["title"] + " " + rule["text"][:200]) and not any(
        p["field"] in ("truck.front_in_strip", "person.distance_m") for p in preds
    ):
        return {
            "route": "out",
            "predicates": [],
            "seat": "grammar",
            "why": "names paperwork, settings or truck care, not something video measures",
        }
    if not preds:
        return {
            "route": "out",
            "predicates": [],
            "seat": "grammar",
            "why": "names no measurable field",
        }
    route = "scan" if "contact" in hay.lower() and "truck" not in hay.lower() else "window"
    return {"route": route, "predicates": [{"all": preds}], "seat": "grammar"}


def _pick_spans(o, text: str):
    """The key may give a span as a list of alternatives, one per copy of a rule's text (the
    faultline pack and the candidate's v2 site pack word the same rule differently). The compiled
    row carries the first alternative that is verbatim in THIS rule's text; if none is, the list
    stays and the checks refuse the row."""
    if isinstance(o, list):
        return [_pick_spans(v, text) for v in o]
    if not isinstance(o, dict):
        return o
    out = {k: _pick_spans(v, text) for k, v in o.items()}
    if isinstance(o.get("span"), list):
        hit = [s for s in o["span"] if _verbatim(s) in text]
        out["span"] = hit[0] if hit else o["span"]
    return out


def script_compile(rule: dict, key: dict | None = None) -> dict:
    key = route_key() if key is None else key
    k = key.get(rule["id"])
    if k is None:
        row = grammar_compile(rule)
    else:
        text = _verbatim(rule.get("title", "") + " \n " + rule["text"])
        row = {
            "route": k["route"],
            "predicates": _pick_spans(k.get("predicates", []), text),
            "seat": "route key",
        }
        if "unless" in k:
            row["unless"] = _pick_spans(k["unless"], text)
        if "why" in k:
            row["why"] = k["why"]
    if row["route"] == "window":
        row["gates"] = GATES
    return row


# -- the model seat
# --------------------------------------------------------------------------------------------------

PROMPT_VERSION = "v3"  # Field meanings, thresholds as {site, span}, every number as {value, span}

FIELD_MEANINGS = {
    "truck.moving": "true while a forklift truck travels",
    "truck.speed_mps": "the truck's ground speed; band high = over the speed limit",
    "truck.reversing": "true while the truck travels against its fork end (backwards)",
    "truck.direction": "forward or reverse",
    "truck.front_in_strip": "true when the truck or its load is inside the touch strip of "
    "racking, uprights, "
    "guards, columns or stacked stock",
    "person.on_foot": "true for a person walking or standing, not riding a truck",
    "person.vested": "true when the person shows a high-visibility band on the torso",
    "person.distance_m": "the person's floor distance to a moving truck's footprint; band under "
    "= closer than "
    "the line",
    "person.in_rear_cone": "a person in the reversing truck's rear path, behind it",
    "person.still": "true for a person standing still",
    "person.in_dock_zone": "true for a person inside a loading-dock zone",
    "contact.consequence": "a visible result of a touch or contact: something shifts or falls, a "
    "vehicle stops "
    "abruptly or spins",
    "camera.static": "the camera did not move",
    "window.one_shot": "the clip window is one continuous shot",
    "window.covers_second": "the window covers the second being ruled",
}
SITE_MEANINGS = {
    "pedestrian_separation_m": "the site's least distance in metres between a moving truck and a "
    "person on foot",
    "speed_limit_mps": "the site speed limit in metres per second",
    "moving_mps": "the speed over which a truck counts as moving",
    "moving_window_s": "how long a movement lasts before it counts, in seconds",
    "stopped_window_s": "how long a truck stands before it counts as stopped",
    "dock_guide_max_mps": "the most speed at a dock",
    "rear_cone_half_angle_deg": "the width of the area behind a reversing truck",
    "structure_strip_m": "how near a structure counts as touching it",
    "consequence_window_s": "how soon after a touch a consequence counts, in seconds",
    "hivis_rule_share": "the share of reads that must lack the band",
}

PROMPT = (
    "You compile rules from a video rules pack into predicates over a CLOSED field "
    "vocabulary. These are the only fields "
    "that exist, with what each measures:\n"
    + "\n".join(f"- {k}: {v}" for k, v in FIELD_MEANINGS.items())
    + "\n\n"
    'A condition is an object: {"field": <a field above>, exactly one test: "is": '
    'true|false, or "band": '
    '"under"|"over"|"high"|"low", or "count_vested": {"value": <how many vested people>, '
    '"span": <rule words that '
    'say that number>}; optionally a threshold "line" (the value the band is read against), '
    '"min" (how long it must '
    'hold) or "within" (how soon after), each written {"site": <a site key below>, "span": '
    "<rule words that name that "
    'quantity>} or {"value": <number from the rule text>, "span": <rule words containing '
    'that number>}; and "span": the '
    'exact words of the rule text the condition comes from}. A predicate is {"all": '
    "[conditions]}; the rule is breached "
    "when any predicate holds.\n"
    "Site keys (a site file holds their values, so a threshold should name one rather than "
    "write its number):\n" + "\n".join(f"- {k}: {v}" for k, v in SITE_MEANINGS.items()) + "\n\n"
    "Every span is copied character for character from the rule's own title or text. No "
    "number appears anywhere except as "
    'a "value" with its own span.\n'
    'route is "window" (the breach can be seen in a fixed-camera clip of a warehouse floor '
    "and written with the fields "
    'above), "scan" (a contact between cars in a racing broadcast, found by a scan for '
    'contact.consequence) or "out" '
    "(paperwork, settings, chat, truck care, procedures, or any breach the fields cannot "
    "write). An out rule has no "
    "predicates. Never invent a field. camera.static, window.one_shot and "
    "window.covers_second are gates the compiler "
    "adds to every window rule itself; leave them out of predicates.\n"
    'Answer with one JSON object and nothing else: {"rules": [{"id": <rule id>, "route": '
    '..., "predicates": [...]}, ...]}, '
    "one entry per rule below, in the same order.\n\n"
)


def batch_prompt(rules: list[dict]) -> str:
    return PROMPT + "\n\n".join(
        f"### Rule id: {r['id']}\nTitle: {r['title']}\n\n{r['text']}" for r in rules
    )


def rule_record(record_dir: Path, rule: dict) -> Path:
    return Path(record_dir) / PROMPT_VERSION / "rules" / f"{rule['id']}.{text_sha(rule)[:12]}.json"


def _parse_reply(text: str) -> dict[str, dict]:
    s, e = text.find("{"), text.rfind("}")
    try:
        obj = json.loads(text[s : e + 1]) if 0 <= s < e else None
    except ValueError:
        obj = None
    rows = obj.get("rules") if isinstance(obj, dict) else obj if isinstance(obj, list) else None
    out = {}
    for r in rows or []:
        if isinstance(r, dict) and isinstance(r.get("id"), str):
            out.setdefault(r["id"], r)
    return out


TESTS = ("is", "band", "count_vested")
THRESHOLDS = ("line", "min", "within")


def _threshold_ok(t) -> bool:
    if not isinstance(t, dict) or not isinstance(t.get("span"), str):
        return False
    if "site" in t:
        return isinstance(t["site"], str) and set(t) <= {"site", "span"}
    return (
        isinstance(t.get("value"), (int, float))
        and not isinstance(t.get("value"), bool)
        and set(t) <= {"value", "span"}
    )


def _valid(obj, rule: dict | None = None, sites=None) -> dict | None:
    """A model proposal, kept only in the grammar's shape, inside the vocabulary, every span and
    number checked by content.
    """
    if not isinstance(obj, dict) or obj.get("route") not in ROUTES:
        return None
    preds = obj.get("predicates", [])
    if not isinstance(preds, list):
        return None
    clean = []
    for p in preds:
        if not isinstance(p, dict) or not isinstance(p.get("all"), list) or not p["all"]:
            return None
        conds = []
        for c in p["all"]:
            if not isinstance(c, dict) or c.get("field") not in VOCAB:
                return None
            if sum(k in c for k in TESTS) != 1 or not isinstance(c.get("span"), str):
                return None
            if "is" in c and not isinstance(c["is"], bool):
                return None
            if "band" in c and c["band"] not in BANDS:
                return None
            if "count_vested" in c and not (
                _threshold_ok(c["count_vested"]) and "value" in c["count_vested"]
            ):
                return None
            if any(k in c and not _threshold_ok(c[k]) for k in THRESHOLDS):
                return None
            conds.append({k: c[k] for k in ("field", *TESTS, *THRESHOLDS, "span") if k in c})
        clean.append({"all": sorted(conds, key=lambda c: c["field"])})
    row = {"route": obj["route"], "predicates": clean if obj["route"] != "out" else []}
    if row["route"] != "out" and not row["predicates"]:
        return None
    if rule is not None and problems(row, rule, sites if sites is not None else _site_values()):
        return None
    return row


def _test_of(c: dict) -> dict:
    """A condition's field and test, thresholds and spans aside; a count is compared by its
    number.
    """
    out = {"field": c["field"]}
    for k in TESTS:
        if k in c:
            out[k] = c[k]["value"] if isinstance(c[k], dict) else c[k]
    return out


def _sig(p: dict) -> str:
    preds = sorted(
        json.dumps(
            sorted((_test_of(c) for c in q["all"]), key=lambda c: json.dumps(c, sort_keys=True)),
            sort_keys=True,
        )
        for q in p["predicates"]
    )
    return json.dumps([p["route"], preds])


def signature(p: dict | None) -> str | None:
    """What three runs must agree on: route, fields and their tests. Spans and the form of a
    threshold may differ.
    """
    return None if p is None else _sig(p)


def key_signature(p: dict) -> str:
    """What a model proposal and the route key are compared on: the same as three runs agree on."""
    return _sig(p)


def ask_model(rules: list[dict], record_dir: Path) -> dict:
    """Spark Open, ten rules a call, three runs a batch; each rule's replies land in its own record
    file. Returns spend.
    """
    todo = [r for r in rules if not rule_record(record_dir, r).exists()]
    seen, uniq = set(), []
    for r in todo:
        if (r["id"], text_sha(r)) not in seen:
            seen.add((r["id"], text_sha(r)))
            uniq.append(r)
    spent = 0.0
    for b in range(0, len(uniq), BATCH):
        batch = uniq[b : b + BATCH]
        prompt = batch_prompt(batch)
        runs = []
        for i in range(RUNS):
            msgs = [
                {
                    "role": "user",
                    "content": prompt + ("" if i == 0 else f"\n\n(independent run {i + 1})"),
                }
            ]
            r = client.chat(
                msgs,
                model=MODEL,
                max_tokens=MAX_TOKENS,
                temperature=0.0,
                tag=f"compile:batch{b // BATCH}:{i + 1}",
                extra={"reasoning_effort": EFFORT},
            )
            spent += r["est_usd"]
            runs.append(
                {
                    "reply": r["text"],
                    "finish": r["finish"],
                    "usage": r["usage"],
                    "est_usd": round(r["est_usd"], 6),
                    "cache": r["cache"],
                }
            )
        parsed = [_parse_reply(x["reply"]) for x in runs]
        bsha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        for rule in batch:
            p = rule_record(record_dir, rule)
            p.parent.mkdir(parents=True, exist_ok=True)
            doc = {
                "id": rule["id"],
                "text_sha256": text_sha(rule),
                "model": MODEL,
                "batch_prompt_sha256": bsha,
                "batch_ids": [x["id"] for x in batch],
                "max_tokens": MAX_TOKENS,
                "reasoning_effort": EFFORT,
                "prompt_version": PROMPT_VERSION,
                "runs": [
                    {"proposal": parsed[i].get(rule["id"]), "finish": runs[i]["finish"]}
                    for i in range(RUNS)
                ],
            }
            p.write_text(
                json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
            )
        braw = Path(record_dir) / PROMPT_VERSION / "batches" / f"{bsha[:16]}.json"
        braw.parent.mkdir(parents=True, exist_ok=True)
        braw.write_text(
            json.dumps(
                {"prompt_sha256": bsha, "ids": [x["id"] for x in batch], "runs": runs},
                indent=1,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(
            f"compile batch {b // BATCH + 1}: {len(batch)} rules, ${spent:.4f} so far", flush=True
        )
    return {"spent": spent}


def model_seat(rule: dict, record_dir: Path | None, sites: set[str]) -> dict | None:
    """The recorded three runs for this rule, if any: agreement count and, on 3 of 3, the shipped
    proposal.
    """
    if record_dir is None:
        return None
    p = rule_record(record_dir, rule)
    if not p.exists():
        return None
    doc = json.loads(p.read_text(encoding="utf-8"))
    props = [_valid(r.get("proposal"), rule, sites) for r in doc["runs"]]
    sigs = [signature(x) for x in props]
    counted = Counter(s for s in sigs if s is not None)
    top, n = counted.most_common(1)[0] if counted else (None, 0)
    out = {"agreement": n, "runs": len(sigs), "refused": sum(s is None for s in sigs)}
    if n == RUNS and len(sigs) == RUNS:
        shipped = props[sigs.index(top)]
        out["proposal"] = shipped
    return out


# -- the pack, compiled
# ------------------------------------------------------------------------------------------------


def compile_pack(pack: dict, use_model: bool = False, record_dir: Path | None = None) -> dict:
    """Every rule: the key's route and predicates, the model's agreement count, the model's
    predicate where 3 of 3 agree.
    """
    key, sites = route_key(), _site_values()
    if use_model and record_dir is not None:
        try:
            ask_model(pack["rules"], record_dir)
        except (client.ApiError, client.BudgetSpent) as exc:
            print(f"model seat stopped: {exc}", flush=True)
    out = {
        "pack": pack["name"],
        "version": pack["version"],
        "domain": pack["domain"],
        "vocabulary": VOCAB,
        "rules": [],
    }
    for rule in pack["rules"]:
        row = script_compile(rule, key)
        bad = problems(row, rule, sites)
        if bad:  # a grammar row that cannot be spanned or names nothing goes out, never as bait
            row = {
                "route": "out",
                "predicates": [],
                "seat": row["seat"],
                "why": "refused by the checks: " + "; ".join(bad),
            }
        ms = model_seat(rule, record_dir, sites)
        if ms is None:
            row["agreement"] = 0
            row["runs"] = 0
            row["model_note"] = "no recorded model runs for this rule text"
        else:
            row["agreement"] = ms["agreement"]
            row["runs"] = ms["runs"]
            if "proposal" in ms:
                prop = ms["proposal"]
                same = key_signature(prop) == key_signature(
                    {"route": row["route"], "predicates": row["predicates"]}
                )
                row["model"] = {
                    **prop,
                    "seat": f"model, {RUNS} of {RUNS} runs agree",
                    "agrees_with_key": same,
                    "route_agrees": prop["route"] == row["route"],
                }
            else:
                row["model_note"] = (
                    f"no model predicate ships: {ms['agreement']} of {ms['runs']} runs "
                    f"agree, {ms['refused']} refused by the checks"
                )
        kind = kind_of(row["predicates"]) if row["route"] == "window" else None
        if kind:
            row["kind"] = kind
        out["rules"].append({"id": rule["id"], "title": rule["title"], **row})
    for r, rule in zip(out["rules"], pack["rules"], strict=False):
        bad = problems(r, rule, sites) + (
            problems(
                {"route": r["model"]["route"], "predicates": r["model"]["predicates"]}, rule, sites
            )
            if "model" in r
            else []
        )
        assert not bad, (r["id"], bad)
    return out
