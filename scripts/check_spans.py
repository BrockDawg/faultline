"""Provenance by value: the checker for a compiled predicates.json (extends the checker).

    uv run python scripts/check_spans.py <predicates.json> [packs_root|pack.md] [site.json]
    [--racing]

Written before the compiler was changed; its rules are the pass mark, so they are
not tuned to the result.

Every compiled row (the route key's predicates, `unless`, `gates`, and a shipped model proposal) is
walked, and each of these is a failure:

1. invented field: a `field` outside the closed vocabulary.
2. bare literal: a number (int or float, not a bool) that is not the `value` of a dict carrying its
   OWN `span`.
3. weak span, by value. A span is weak when
   a. it is not a verbatim substring of its rule's own pack text (title or body; markdown `*`
      removed and runs of whitespace collapsed, case kept), or
   b. it belongs to a literal `{value, span}` and holds neither the number as written nor its number
      word, or
   c. it belongs to a threshold `{site, span}` and holds neither the site's value as a number nor
      its number word, unless (rule id, site key) is in the explicit site table
      (assets/site_table.json) and the span IS that table's sentence: verbatim in the rule's text
      and holding the word "site" (the pack leaves the value to the site).
      A quantity word ("metres", "moving", "behind") no longer names a value; the QUANTITY_WORDS
      path is gone.
      A threshold with no span, or the `{site, explicit}` form, is weak, unless (rulings 2 and 6)
      the (rule id, site key) is declared in assets/site_values.json: then it is listed as an
      explicit site value with no span, and it is a site fault if its rule's text holds the site's
      value as a number (the value has not left the text).
4. site-key faults: a `{site}` key unknown to site.json, a boolean site key used as a threshold, a
   site switch whose site value is not a boolean, a `policy` naming a numeric site key; an explicit
   site table entry no compiled row uses, or one whose sentence is not in its rule's text or does
   not hold "site"; a `measuring` key unknown to site.json or also used as a predicate threshold.

The `measuring` table (field -> site keys) is printed: site values that set how a vocabulary field
is measured (measure.py reads them from site.json) and that no rule sentence holds or leaves to the
site. They are not thresholds.

--racing adds the per-rule racing report (criteria fixed before it was run).
"""

import json
import re
import sys
from pathlib import Path

VOCAB = {
    "truck.moving",
    "truck.speed_mps",
    "truck.reversing",
    "truck.direction",
    "truck.front_in_strip",
    "person.on_foot",
    "person.vested",
    "person.distance_m",
    "person.in_rear_cone",
    "person.still",
    "person.in_dock_zone",
    "contact.consequence",
    "camera.static",
    "window.one_shot",
    "window.covers_second",
}

NUMBER_WORDS = {
    0: ["no ", "none", "zero", "nobody", "no one"],
    0.5: ["half"],
    1: ["one", "a second", "a metre", "single"],
    2: ["two"],
    3: ["three"],
}
CAND = Path(__file__).resolve().parents[1]

# racing report: the words that name a contact between cars, and each field's words
CONTACT_WORDS = (
    r"\b(?:contact|wreck\w*|bump\w*|punt\w*|spin\w*|collision\w*|crash\w*|hit\w*|door\w*)\b"
)
FIELD_WORDS = {"contact.consequence": CONTACT_WORDS}
RACING_PACKS = ("open-wheel", "oval", "road-gt")


def norm(s: str) -> str:
    return " ".join(str(s).replace("*", "").split())


def num_text(v) -> list[str]:
    out = [repr(v)]
    if isinstance(v, float) and v.is_integer():
        out.append(str(int(v)))
    return out


def names_number(span: str, v) -> bool:
    """The span holds v as a number (not as part of a longer number) or as its number word."""
    s = norm(span)
    if any(re.search(rf"(?<![\d.]){re.escape(t)}(?!\d|\.\d)", s) for t in num_text(v)):
        return True
    low = s.lower() + " "
    return any(w in low for w in NUMBER_WORDS.get(v, []))


def load_texts(root: Path) -> dict[str, list[tuple[str, str]]]:
    """rule id -> [(pack folder, normalised title + body)], one per copy of the rule."""
    texts: dict[str, list[tuple[str, str]]] = {}
    root = Path(root)
    files = [root] if root.is_file() else sorted(root.rglob("*.md"))
    for p in files:
        if p.name.lower() == "readme.md":
            continue
        raw = p.read_text(encoding="utf-8")
        parts = re.split(r"\n(?=---\s*\nid:)", "\n" + raw) if root.is_file() else [raw]
        for t in parts:
            m = re.match(r"\s*---\s*\n(.*?)\n---\s*\n(.*)\Z", t.strip() + "\n", re.S)
            if not m:
                continue
            meta = {}
            for ln in m.group(1).splitlines():
                k, sep, v = ln.partition(":")
                if sep:
                    meta[k.strip()] = v.strip()
            texts.setdefault(meta.get("id", p.stem), []).append(
                (p.parent.name, norm(meta.get("title", "") + " \n " + m.group(2)))
            )
    return texts


def load_table(path=None) -> dict[tuple[str, str], str]:
    p = Path(path) if path else CAND / "src/faultline/adapters/video/data/site_table.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    return {(e["rule"], e["site"]): e["sentence"] for e in d["entries"]}


def value_in_text(v: float, texts: list[str]) -> bool:
    """A site value written in a rule's text: as a number (0.1, 0.10, 0.30) or, for a share, as a
    percentage (70%); the pack's placeholder brackets are ignored."""
    forms = {repr(v), f"{v:.1f}", f"{v:.2f}"}
    if 0 < v < 1:
        forms |= {f"{round(v * 100)}%", f"{round(v * 100)} %", f"{round(v * 100)} per cent"}
    for t in texts:
        t = t.replace("[", "").replace("]", "")
        if any(re.search(rf"(?<![\d.]){re.escape(f)}(?!\d)", t) for f in forms):
            return True
    return False


def load_declared(path=None) -> dict[tuple[str, str], str]:
    """(Rulings 2 and 6): the declared explicit site values, (rule id, site key) -> why."""
    p = Path(path) if path else CAND / "src/faultline/adapters/video/data/site_values.json"
    if not p.exists():
        return {}
    return {
        (e["rule"], e["site"]): e["why"]
        for e in json.loads(p.read_text(encoding="utf-8"))["values"]
    }


def check_row(
    rid: str,
    row: dict,
    texts: list[str],
    site: dict,
    table: dict,
    used: set,
    declared: dict | None = None,
    dused: set | None = None,
) -> dict[str, list[str]]:
    declared = declared or {}
    dused = set() if dused is None else dused
    bad = {"invented": [], "bare": [], "weak": [], "site": [], "explicit": []}

    def in_text(span):
        return any(norm(span) in t for t in texts)

    def walk(o, key=None):
        if isinstance(o, bool) or o is None or isinstance(o, str):
            return
        if isinstance(o, (int, float)):
            bad["bare"].append(f"{key}={o}")
            return
        if isinstance(o, list):
            for v in o:
                walk(v, key)
            return
        if "field" in o and o["field"] not in VOCAB:
            bad["invented"].append(o["field"])
        if "span" in o and o["span"] is not None and not in_text(o["span"]):
            bad["weak"].append(f"not in the rule text: {o['span']!r}")
        if "switch" in o:
            sw = o["switch"]
            if (
                not isinstance(sw, dict)
                or sw.get("site") not in site
                or not isinstance(site.get(sw.get("site")), bool)
            ):
                bad["site"].append(f"switch not a boolean site key: {sw!r}")
        if "policy" in o:
            k = o["policy"]
            if k not in site:
                bad["site"].append(f"site policy unknown: {k!r}")
            elif isinstance(site[k], (int, float)) and not isinstance(site[k], bool):
                bad["site"].append(
                    f"policy {k!r} names a numeric site key (a threshold with no span)"
                )
        if "site" in o:
            k = o["site"]
            sp = o.get("span")
            if k not in site:
                bad["site"].append(f"site key unknown: {k!r}")
            elif isinstance(site[k], bool):
                bad["site"].append(
                    f"boolean site key {k!r} used as a threshold; a site setting is a switch"
                )
            elif "explicit" in o and (rid, k) in declared and not sp:
                dused.add((rid, k))
                if isinstance(site[k], (int, float)) and value_in_text(site[k], texts):
                    bad["site"].append(
                        f"declared site value {k} = {site[k]!r}, but its rule's text holds "
                        "the value"
                    )
                else:
                    bad["explicit"].append(
                        f"{k} = {site[k]!r} (declared site value, no span: {declared[(rid, k)]})"
                    )
            elif "explicit" in o:
                bad["weak"].append(
                    f"threshold {k} in the explicit form: no span, so no value to check"
                )
            elif not sp:
                bad["weak"].append(f"threshold {k} has no span")
            elif names_number(sp, site[k]):
                pass
            elif (
                (rid, k) in table
                and norm(table[(rid, k)]) == norm(sp)
                and "site" in norm(sp).lower()
            ):
                used.add((rid, k))
                bad["explicit"].append(f"{k} = {site[k]!r} (left to the site by: {sp!r})")
            else:
                bad["weak"].append(
                    f"threshold {k} = {site[k]!r} spanned by {sp!r}, which does not hold the value"
                    + ("" if (rid, k) in table else " and is not in the explicit site table")
                )
        if (
            "value" in o
            and isinstance(o["value"], (int, float))
            and not isinstance(o["value"], bool)
        ):
            sp = o.get("span")
            if not sp:
                bad["bare"].append(f"value {o['value']} with no span of its own")
            elif not names_number(sp, o["value"]):
                bad["weak"].append(f"value {o['value']} spanned by {sp!r}, which does not hold it")
        for k, v in o.items():
            if k == "switch" or (k == "value" and isinstance(v, (int, float))):
                continue
            walk(v, k)

    for part in ("predicates", "unless", "gates"):
        if part in row:
            walk(row[part], part)
    if "model" in row:
        walk(row["model"].get("predicates", []), "model")
    return bad


def racing_report(rows: list[dict], texts: dict) -> list[str]:
    print("\nracing report (criteria fixed before it was run)")
    print("pack / rule / route / fields named by the rule's words / route supported by the text")
    unsupported = []
    for r in rows:
        pack = str(r.get("pack", "")).removeprefix(
            "pitbot-library-"
        )  # pack.json names the racing packs pitbot-library-<folder>
        if pack not in RACING_PACKS:
            continue
        rid = r.get("id") or r.get("rule")
        copies = [t for f, t in texts.get(rid, []) if f == pack]
        if not copies:
            continue
        text = copies[0]
        hit = re.search(CONTACT_WORDS, text, re.I)
        fields = []
        for p in r.get("predicates", []):
            for c in p.get("all", []):
                w = FIELD_WORDS.get(c["field"])
                named = bool(w and c.get("span") and re.search(w, c["span"], re.I))
                fields.append(
                    f"{c['field']} {'named' if named else 'NOT NAMED'} by {c.get('span')!r}"
                )
        route = r["route"]
        if route == "window":
            ok, why = False, "a racing rule has no fixed camera or floor plane"
        elif route == "scan":
            ok = bool(hit) and all("NOT NAMED" not in f for f in fields)
            why = (
                "the text names a contact and each field's span names it"
                if ok
                else "the text or a span names no contact"
            )
        else:
            ok = not hit
            why = (
                "the text names no contact between cars"
                if ok
                else f"text names a contact the scan could flag ({hit.group(0)!r})"
            )
        if not ok:
            unsupported.append(f"{pack}/{rid}")
        print(
            f"  {pack:10s} {rid:30s} {route:5s} {'; '.join(fields) or '-'} | "
            f"{'supported' if ok else 'NOT SUPPORTED'}: {why}"
        )
    print(f"racing rules whose route the text does not support ({len(unsupported)}): {unsupported}")
    return unsupported


def main(*argv):
    racing = "--racing" in argv
    argv = [a for a in argv if a != "--racing"]
    path = argv[0]
    root = argv[1] if len(argv) > 1 else str(CAND / "packs")
    site_path = argv[2] if len(argv) > 2 else CAND / "src/faultline/adapters/video/data/site.json"
    site = json.loads(Path(site_path).read_text(encoding="utf-8"))
    table = load_table()
    declared = load_declared()
    dused: set = set()
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = (
        d
        if isinstance(d, list)
        else d.get("rules") or [r for p in d.get("packs", []) for r in p["rules"]]
    )
    measuring = {}
    if isinstance(d, dict):
        measuring = (
            d.get("measuring") or (d["packs"][0].get("measuring") if d.get("packs") else None) or {}
        )
    texts = load_texts(Path(root))
    tot = {"invented": 0, "bare": 0, "weak": 0, "site": 0, "explicit": 0}
    used: set = set()
    thresholds: set = set()
    parsed = 0
    rids = set()
    for r in rows:
        rid = r.get("id") or r.get("rule")
        rids.add(rid)
        parsed += r.get("route") in ("scan", "window", "out") and (
            r["route"] == "out" or bool(r.get("predicates"))
        )
        t = texts.get(rid)
        if t is None:
            print(f"  {rid}: weak: no pack text under {root}")
            tot["weak"] += 1
            continue
        for k, v in check_row(
            rid, r, [x for _, x in t], site, table, used, declared, dused
        ).items():
            tot[k] += len(v)
            for x in v:
                print(f"  {rid}: {k}: {x}")
        for m in re.finditer(
            r'"site": "([^"]+)"', json.dumps({k: r.get(k) for k in ("predicates", "model")})
        ):
            thresholds.add(m.group(1))
    # the explicit site table: every entry for a rule compiled here is used, and its sentence is in
    # the rule and says "site"
    for (rid, k), sent in sorted(table.items()):
        if rid not in rids:
            continue
        if (
            not any(norm(sent) in x for _, x in texts.get(rid, []))
            or "site" not in norm(sent).lower()
        ):
            print(
                f"  {rid}: site: explicit site table sentence not in the rule text or holds "
                f"no 'site': {sent!r}"
            )
            tot["site"] += 1
        elif (rid, k) not in used:
            print(f"  {rid}: site: explicit site table entry {k} used by no compiled threshold")
            tot["site"] += 1
    for rid, k in sorted(declared):
        if rid in rids and (rid, k) not in dused:
            print(f"  {rid}: site: declared site value {k} used by no compiled threshold")
            tot["site"] += 1
    for field, keys in sorted(measuring.items()):
        for k in keys:
            if k not in site:
                print(f"  measuring: site: {field} names unknown site key {k!r}")
                tot["site"] += 1
            elif k in thresholds:
                print(f"  measuring: site: {k} is also a predicate threshold")
                tot["site"] += 1
    print(
        "measuring constants (site values that set how a field is measured; not rule "
        "thresholds, no pack sentence): "
        + (
            "; ".join(
                f"{f}: {', '.join(f'{k}={site.get(k)!r}' for k in ks)}"
                for f, ks in sorted(measuring.items())
            )
            or "none listed"
        )
    )
    ex = sorted(f"{rid}:{k}" for rid, k in used | dused)
    print(
        f"rules {len(rows)}; parsed {parsed} of {len(rows)}; invented fields "
        f"{tot['invented']}; bare literals {tot['bare']}; "
        f"weak spans by value {tot['weak']}; site-key faults {tot['site']}; explicit site "
        f"values {tot['explicit']} "
        f"({', '.join(ex) or 'none'})"
    )
    if racing:
        racing_report(rows, texts)
    return 0 if not any(v for k, v in tot.items() if k != "explicit") and parsed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:]))
