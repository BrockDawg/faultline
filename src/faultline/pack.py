"""Load rules packs: a folder of markdown rule files plus a `pack.json`.

A pack folder holds:

- `pack.json`: a JSON object with non-empty string `name`, `version` and `domain`, an optional
  string `source`, and an optional boolean `unique_ids_across_domain`. Other keys are ignored.
- one or more `*.md` rule files, read in file-name order. Each opens with a `---` line, then
  `key: value` header lines (blank lines allowed), a closing `---`, then the rule text.
  The header must hold a non-empty `id` and `title`; other header keys are ignored.

Files are read as UTF-8 (a byte order mark is tolerated), with LF, CRLF or mixed line endings.
Returned text always uses `\\n`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Pack", "PackError", "Rule", "load_pack", "load_packs"]

_FENCE = "---"
_SOURCE_PREFIX = "Source:"
_REQUIRED_PACK_FIELDS = ("name", "version", "domain")
_REQUIRED_RULE_KEYS = ("id", "title")
_CROSS_CHECK_KEY = "unique_ids_across_domain"


class PackError(ValueError):
    """A rules pack could not be loaded; the message names the file or folder and the reason."""


@dataclass(frozen=True)
class Rule:
    """One rule from a pack: its id, title, full text and the `Source:` clause if it has one."""

    id: str
    title: str
    text: str
    source_clause: str | None


@dataclass(frozen=True)
class Pack:
    """A loaded rules pack: its metadata from `pack.json` and its rules in file-name order."""

    name: str
    version: str
    domain: str
    source: str | None
    rules: tuple[Rule, ...]
    unique_ids_across_domain: bool = False


def _read_text(path: Path) -> str:
    """Read a file as UTF-8 (BOM tolerated) and turn CRLF and lone CR line endings into LF."""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise PackError(f"{path}: could not be read ({exc.strerror or exc}).") from exc
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise PackError(f"{path}: is not valid UTF-8 text.") from exc
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _load_pack_json(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise PackError(f"{path.parent}: has no pack.json file.")
    try:
        data = json.loads(_read_text(path))
    except json.JSONDecodeError as exc:
        raise PackError(
            f"{path}: is not valid JSON (line {exc.lineno}, column {exc.colno}: {exc.msg})."
        ) from exc
    if not isinstance(data, dict):
        raise PackError(f"{path}: must hold a JSON object, not {type(data).__name__}.")
    for field in _REQUIRED_PACK_FIELDS:
        value = data.get(field)
        if field not in data:
            raise PackError(f"{path}: the required field {field!r} is missing.")
        if not isinstance(value, str) or not value.strip():
            raise PackError(f"{path}: the required field {field!r} must be a non-empty string.")
    source = data.get("source")
    if source is not None and not isinstance(source, str):
        raise PackError(f"{path}: the field 'source' must be a string when present.")
    flag = data.get(_CROSS_CHECK_KEY, False)
    if not isinstance(flag, bool):
        raise PackError(
            f"{path}: the field {_CROSS_CHECK_KEY!r} must be true or false when present."
        )
    return data


def _parse_rule(path: Path) -> Rule:
    lines = _read_text(path).split("\n")
    if not lines or lines[0].strip() != _FENCE:
        raise PackError(f"{path}: a rule file must open with a '---' line.")
    header: dict[str, str] = {}
    closing = None
    for index in range(1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if stripped == _FENCE:
            closing = index
            break
        if not stripped:
            continue
        if ":" not in line:
            raise PackError(
                f"{path}: header line {index + 1} ({stripped!r}) has no ':' "
                "and is not a 'key: value' line."
            )
        key, _, value = line.partition(":")
        header[key.strip()] = value.strip()
    if closing is None:
        raise PackError(f"{path}: the header has no closing '---' line.")
    for key in _REQUIRED_RULE_KEYS:
        if key not in header:
            raise PackError(f"{path}: the header has no {key!r}.")
        if not header[key]:
            raise PackError(f"{path}: the header's {key!r} is blank.")
    text = "\n".join(lines[closing + 1 :]).strip()
    if not text:
        raise PackError(f"{path}: there is no rule text after the header.")
    source_clause = None
    for line in text.split("\n"):
        if line.startswith(_SOURCE_PREFIX):
            source_clause = line[len(_SOURCE_PREFIX) :].strip()
            break
    return Rule(id=header["id"], title=header["title"], text=text, source_clause=source_clause)


def load_pack(folder: str | Path) -> Pack:
    """Load one pack folder. Raises `PackError` naming the file or folder and the reason."""
    path = Path(folder)
    if not path.exists():
        raise PackError(f"{path}: the pack folder does not exist.")
    if not path.is_dir():
        raise PackError(f"{path}: is not a folder, so it cannot be a pack.")
    meta = _load_pack_json(path / "pack.json")
    rule_files = sorted((p for p in path.glob("*.md") if p.is_file()), key=lambda p: p.name)
    if not rule_files:
        raise PackError(f"{path}: has no *.md rule files.")
    rules: list[Rule] = []
    seen: dict[str, Path] = {}
    for rule_file in rule_files:
        rule = _parse_rule(rule_file)
        if rule.id in seen:
            raise PackError(
                f"{path}: the rule id {rule.id!r} appears twice, "
                f"in {seen[rule.id].name} and in {rule_file.name}."
            )
        seen[rule.id] = rule_file
        rules.append(rule)
    source = meta.get("source")
    return Pack(
        name=str(meta["name"]).strip(),
        version=str(meta["version"]).strip(),
        domain=str(meta["domain"]).strip(),
        source=source if isinstance(source, str) else None,
        rules=tuple(rules),
        unique_ids_across_domain=bool(meta.get(_CROSS_CHECK_KEY, False)),
    )


def load_packs(root: str | Path, domain: str | None = None) -> tuple[Pack, ...]:
    """Load every immediate sub-folder of `root` holding a `pack.json`, sorted by folder name.

    With `domain`, only packs of that domain are returned. Among the returned packs flagged
    `unique_ids_across_domain`, two packs of the same domain sharing a rule id raise `PackError`.
    """
    base = Path(root)
    if not base.exists():
        raise PackError(f"{base}: the packs folder does not exist.")
    if not base.is_dir():
        raise PackError(f"{base}: is not a folder, so it cannot hold packs.")
    folders = sorted(
        (p for p in base.iterdir() if p.is_dir() and (p / "pack.json").is_file()),
        key=lambda p: p.name,
    )
    loaded: list[tuple[Path, Pack]] = [(folder, load_pack(folder)) for folder in folders]
    if domain is not None:
        loaded = [(folder, pack) for folder, pack in loaded if pack.domain == domain]
    owners: dict[tuple[str, str], Path] = {}
    for folder, pack in loaded:
        if not pack.unique_ids_across_domain:
            continue
        for rule in pack.rules:
            key = (pack.domain, rule.id)
            if key in owners:
                raise PackError(
                    f"{base}: the rule id {rule.id!r} appears in two packs of domain "
                    f"{pack.domain!r}, {owners[key].name} and {folder.name}, "
                    "and both ask for ids unique across the domain."
                )
            owners[key] = folder
    return tuple(pack for _, pack in loaded)
