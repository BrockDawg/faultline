"""The ruling lifecycle: identified, confirmed or denied, disputed, final, with only the allowed
transitions.

A breach ruling enters as `identified`. The insurer confirms or denies it; only a confirmed ruling
can be disputed, and only by the site; the insurer closes a ruling as `final`, after which nothing
moves. The same table is embedded in the dashboard, so the page and this module refuse the same
moves.

    faultline lifecycle <lifecycle.json> <ruling> <to> --by insurer|site [--note TEXT]
    faultline lifecycle <lifecycle.json> --show
"""

from __future__ import annotations

import json
from pathlib import Path

STATES = ("identified", "confirmed", "denied", "disputed", "final")

# from-state -> {to-state: the one party allowed to make that move}
TRANSITIONS: dict[str, dict[str, str]] = {
    "identified": {"confirmed": "insurer", "denied": "insurer"},
    "confirmed": {"disputed": "site", "final": "insurer"},
    "denied": {"final": "insurer"},
    "disputed": {"final": "insurer"},
    "final": {},
}

PARTIES = ("insurer", "site")


class IllegalTransition(ValueError):
    pass


def ruling_key(window: str, rule: str) -> str:
    return f"{window}/{rule}"


def initial(preds: list[dict]) -> dict:
    """Every breach ruling of the shift, identified; clear and unable rulings carry no lifecycle."""
    rulings = {}
    for line in preds:
        for r in line["rulings"]:
            if r["verdict"] == "breach":
                rulings[ruling_key(line["id"], r["rule"])] = {
                    "window": line["id"],
                    "rule": r["rule"],
                    "state": "identified",
                    "history": [],
                }
    return {
        "lifecycle": "faultline 1",
        "states": list(STATES),
        "transitions": TRANSITIONS,
        "rulings": rulings,
    }


def check(state: str, to: str, by: str) -> None:
    if state not in TRANSITIONS:
        raise IllegalTransition(f"unknown state {state!r}")
    if to not in STATES:
        raise IllegalTransition(f"unknown state {to!r}")
    allowed = TRANSITIONS[state]
    if to not in allowed:
        nxt = (
            ", ".join(f"{k} (by {v})" for k, v in allowed.items())
            or "nothing; a final ruling never moves"
        )
        raise IllegalTransition(
            f"{state} -> {to} is not an allowed move; from {state} the allowed moves are: {nxt}"
        )
    if allowed[to] != by:
        raise IllegalTransition(f"{state} -> {to} is made by the {allowed[to]}, not the {by}")


def apply(doc: dict, key: str, to: str, by: str, note: str = "", at: str = "") -> dict:
    """Move one ruling; raises IllegalTransition and leaves `doc` untouched when the move is not
    allowed.
    """
    if key not in doc["rulings"]:
        raise IllegalTransition(f"no ruling {key!r} in this lifecycle")
    if by not in PARTIES:
        raise IllegalTransition(f"unknown party {by!r}; the parties are {', '.join(PARTIES)}")
    r = doc["rulings"][key]
    check(r["state"], to, by)
    r["history"].append({"from": r["state"], "to": to, "by": by, "note": note, "at": at})
    r["state"] = to
    return doc


def load(p: Path) -> dict:
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save(doc: dict, p: Path) -> None:
    Path(p).write_text(
        json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )


def cmd(args) -> int:
    import datetime
    import sys

    p = Path(args.file)
    doc = load(p)
    if args.show or not args.ruling:
        for k, r in sorted(doc["rulings"].items()):
            print(f"{k}: {r['state']}" + (f"  ({len(r['history'])} moves)" if r["history"] else ""))
        return 0
    if not args.to or not args.by:
        print("give the state to move to and --by insurer|site", file=sys.stderr)
        return 2
    try:
        apply(
            doc,
            args.ruling,
            args.to,
            args.by,
            args.note or "",
            datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        )
    except IllegalTransition as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 1
    save(doc, p)
    print(f"{args.ruling}: now {args.to}")
    return 0
