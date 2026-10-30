"""The `faultline` command line: one entry point, domain commands found in the adapters.

`main(argv=None) -> int` builds the parser and runs one command. It holds two kinds:

- `faultline <domain> ...`: each adapter package under `faultline.adapters` that declares a
  string `DOMAIN` (the domain word, such as the one a sport or a site uses) and a string
  `CLI` (the dotted name of its command module, relative to the package, such as ".cli")
  gets a sub-command named by its word. The command module's `register(parser)` adds that
  domain's own sub-commands and sets `func` (a callable taking the parsed namespace and
  returning an exit code) on each. Adapters are found by `pkgutil` and imported by name at
  run time, so this module never imports an adapter. Two adapters claiming one word refuse.
- `faultline replay <preds.jsonl> --out <preds2.jsonl>`: rebuilds every ruling line from its
  bundle alone (see "Bundles" below). No source file, no network, no external tool is read.

Bundles. Every ruling line carries `record`, the sha256 of its bundle, and the bundle sits at
`<preds>.record/<record>.json` (`faultline.record.write_bundle`). A bundle is one JSON object:

- `format`: `BUNDLE_FORMAT`;
- `inputs`: what the ruling was built from, by content only (sha256 of each source file and of
  each source record, the configuration entries without paths, parameters). Never an absolute
  path, never a clock reading. Later stages add keys here (frame file hashes, ledger keys);
  a key named in `VERIFIERS` is also checked by its verifier during replay;
- `ruling`: the ruling line without `record`;
- `detail`: per stage, what that stage worked out beyond the line (an object, keyed by stage
  name, empty when a stage has nothing more), for the next stage and for a reader.

`record` is `record.record_hash(bundle)`, so any change to inputs or ruling changes it.
`bundle_for(inputs, ruling, detail=None)` returns `(record, bundle)`;
`write_rulings(out, pairs)` writes every bundle, then the lines (sorted by the caller), atomically.

Replay reads each line's `id` and `record`, reads the bundle, recomputes the hash and refuses
(`CliError` naming the line id) when the bundle is missing, holds another format, hashes to
another value, names another id, or when the line differs from the ruling its bundle holds.
It writes the rebuilt lines in input order to `--out` and copies each bundle beside it, so the
output is byte-identical to the input when nothing changed and is itself replayable.

Errors: a `ValueError` or `OSError` from any command prints `faultline: <message>` on stderr
and exits 2; every module's error message names the file and the reason, never private text.
"""

from __future__ import annotations

import argparse
import importlib
import json
import pkgutil
import sys
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

from faultline import record

__all__ = [
    "BUNDLE_FORMAT",
    "VERIFIERS",
    "CliError",
    "bundle_for",
    "main",
    "replay",
    "write_rulings",
]

BUNDLE_FORMAT = "faultline.bundle/1"
_ADAPTERS = "faultline.adapters"

# Replay checks for input keys that point at files outside the bundle (frame images in a later
# stage, for example): key -> function(preds path, value of that input) that raises on a miss.
VERIFIERS: dict[str, Callable[[Path, Any], None]] = {}


class CliError(ValueError):
    """A command was refused; the message names the file or line and the reason."""


# ---------------------------------------------------------------- bundles


def bundle_for(
    inputs: dict[str, Any], ruling: dict[str, Any], detail: dict[str, Any] | None = None
) -> tuple[str, dict[str, Any]]:
    """Return `(record, bundle)` for one ruling line built from `inputs`."""
    if "record" in ruling:
        raise CliError(f"ruling {ruling.get('id')!r}: already carries a record.")
    bundle = {"detail": detail or {}, "format": BUNDLE_FORMAT, "inputs": inputs, "ruling": ruling}
    return record.record_hash(bundle), bundle


def write_rulings(out: Path | str, pairs: Iterable[tuple[str, dict[str, Any]]]) -> Path:
    """Write each bundle beside `out`, then every line (`ruling` plus `record`), atomically."""
    rows: list[dict[str, Any]] = []
    for sha, bundle in pairs:
        record.write_bundle(out, sha, bundle)
        rows.append({**bundle["ruling"], "record": sha})
    return record.write_lines_atomic(out, rows)


# ---------------------------------------------------------------- replay


def _read_lines(path: Path) -> list[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"{path}: cannot be read ({exc.strerror or type(exc).__name__}).") from None
    except UnicodeDecodeError:
        raise CliError(f"{path}: is not UTF-8 text.") from None
    rows: list[dict[str, Any]] = []
    for no, line in enumerate(text.split("\n"), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise CliError(f"{path}: line {no} is not JSON.") from None
        if not isinstance(row, dict):
            raise CliError(f"{path}: line {no} is not a JSON object.")
        rows.append(row)
    return rows


def replay(preds: Path | str, out: Path | str) -> Path:
    """Rebuild every line of `preds` from its bundle alone and write them to `out`."""
    src = Path(preds)
    rebuilt: list[tuple[str, dict[str, Any]]] = []
    for row in _read_lines(src):
        rid = row.get("id")
        sha = row.get("record")
        if not isinstance(sha, str):
            raise CliError(f"{src}: line {rid!r} has no record.")
        try:
            bundle = record.read_bundle(src, sha)
        except record.RecordError as exc:
            raise CliError(f"line {rid!r}: {exc}") from None
        if bundle.get("format") != BUNDLE_FORMAT:
            raise CliError(f"line {rid!r}: its bundle is not format {BUNDLE_FORMAT!r}.")
        if record.record_hash(bundle) != sha:
            raise CliError(f"line {rid!r}: its bundle does not hash to its record.")
        inputs, ruling = bundle.get("inputs"), bundle.get("ruling")
        if not isinstance(inputs, dict) or not isinstance(ruling, dict):
            raise CliError(f"line {rid!r}: its bundle has no inputs or no ruling object.")
        if ruling.get("id") != rid:
            raise CliError(f"line {rid!r}: its bundle holds the ruling of another id.")
        if {**ruling, "record": sha} != row:
            raise CliError(f"line {rid!r}: the line differs from the ruling its bundle holds.")
        for key, verify in VERIFIERS.items():
            if key in inputs:
                verify(src, inputs[key])
        rebuilt.append((sha, bundle))
    return write_rulings(out, rebuilt)


def _cmd_replay(args: argparse.Namespace) -> int:
    path = replay(args.preds, args.out)
    print(f"faultline replay: wrote {path}")
    return 0


# ---------------------------------------------------------------- domain discovery


def _domain_modules() -> list[tuple[str, ModuleType]]:
    """(domain word, command module) for every adapter that declares one, sorted by word."""
    package = importlib.import_module(_ADAPTERS)
    found: dict[str, ModuleType] = {}
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda i: i.name):
        if not info.ispkg:
            continue
        adapter = importlib.import_module(f"{_ADAPTERS}.{info.name}")
        word = getattr(adapter, "DOMAIN", None)
        cli_name = getattr(adapter, "CLI", None)
        if not isinstance(word, str) or not isinstance(cli_name, str):
            continue
        if word in found or word == "replay":
            raise CliError(f"adapter {info.name}: the domain word {word!r} is already taken.")
        found[word] = importlib.import_module(cli_name, package=adapter.__name__)
    return sorted(found.items())


def build_parser() -> argparse.ArgumentParser:
    """The full parser: `replay` plus one sub-command per declared domain."""
    parser = argparse.ArgumentParser(prog="faultline", description="A rules judge.")
    commands = parser.add_subparsers(dest="command", required=True, metavar="command")
    rp = commands.add_parser("replay", help="rebuild ruling lines from their bundles only")
    rp.add_argument("preds", type=Path, help="ruling lines to rebuild")
    rp.add_argument("--out", type=Path, required=True, help="where to write the rebuilt lines")
    rp.set_defaults(func=_cmd_replay)
    for word, module in _domain_modules():
        domain = commands.add_parser(word, help=f"commands of the {word} domain")
        module.register(domain)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one `faultline` command and return its exit code."""
    try:
        parser = build_parser()
        args = parser.parse_args(argv)
        func = getattr(args, "func", None)
        if func is None:
            parser.error("name a command")
        return int(func(args))
    except (ValueError, OSError) as exc:
        print(f"faultline: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
