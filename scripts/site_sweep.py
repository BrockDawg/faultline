"""The hygiene sweep over every file the live page serves; writes a stamp only when all pass.

    uv run python scripts/site_sweep.py --bundle site/data --page site --names data/racing

Seven checks, each over every served file (the page folder and the bundle folder):

1. Leak lint (`faultline.lint`): no driver name and no league name. The names are gathered the
   way `scripts/racing_card.py` gathers them from the racing names folder (`league.json` and
   its feeds, `inputs.json` and its pack). A missing or unreadable names source fails closed.
2. Tooling words: none of `TOOLING_WORDS`, case-insensitive, whole word.
3. Banned phrases: the medical and sports patterns of `tests/test_provenance.py`.
4. Numbers: every entry of `numbers` in `index.json` and in `racing.json` (both required) appears on
   its cited README line, the replay hashes sit on theirs, and every number in the page's HTML
   text appears on one of those cited lines.
5. Models: every `words` block and every racing read names its model; the open-weight line is
   verbatim; the four Meta models are in the models list. Racing: no sim session number,
   customer id, stream name or league folder name in any served file, and no racing image.
6. Images: every image is listed in the frames manifest (`frames/frames.json`) with its hash,
   belongs to a clip in `index.json`, and every real-footage frame has `checked: true` in
   `frames/blurred.json`.
7. Secrets: `gitleaks dir` over the page and bundle folders only (refused on any folder that
   holds a `.git` or a `workspaces` folder), no `.env` file, no key variable with a value.

A matched name is never printed: a failure names the file, the check and a count.
The stamp is `<bundle>/.sweep-<bundle sha256>.ok`, with `bundle_sha256` below as the key.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCRIPTS = Path(__file__).resolve().parent
REPO = SCRIPTS.parent
sys.path.insert(0, str(SCRIPTS))

import racing_card as card  # noqa: E402

from faultline import lint  # noqa: E402
from faultline.adapters.pitbot import cli as pitbot  # noqa: E402

STAMP_PREFIX = ".sweep-"
STAMP_SUFFIX = ".ok"
PROVENANCE_TEST = REPO / "tests" / "test_provenance.py"

TOOLING_WORDS = (
    "Claude",
    "Anthropic",
    "Opus",
    "Sonnet",
    "Glitch",
    "Codex",
    "Copilot",
    "Cursor",
    "coding agent",
    "agent-built",
    "tournament",
    "harness",
    "builder",
    "ai-steward",
    "proxy",
    "wave",
    "Higgsfield",
)
_TOOLING = re.compile(
    r"(?<![\w-])(?:"
    + "|".join(r"\s+".join(re.escape(w) for w in word.split()) for word in TOOLING_WORDS)
    + r")(?![\w-])",
    re.IGNORECASE,
)

OPEN_WEIGHT_LINE = (
    "Muse Spark Open is a Meta open-weight model, served by Baseten (partner inference, "
    "model id `meta-models/muse-spark-open-1026`)."
)
REQUIRED_MODELS = ("SAM 3.1", "Muse Spark Open", "Muse Wonder 1.0", "Muse Spark 1.3")

TEXT_SUFFIXES = {".html", ".htm", ".js", ".mjs", ".css", ".json", ".txt", ".svg", ".md", ".map"}
RASTER_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".bmp", ".ico"}
_RASTER_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"\x00\x00\x01\x00")

_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w])")
_HEX_PREFIX = re.compile(r"^[0-9a-f]{8,64}")
_EMAIL = re.compile(r"(?<![\w.+\-])[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_KEY_VALUE = re.compile(
    r"\b[A-Z][A-Z0-9_]*(?:API_KEY|_KEY|_TOKEN|_SECRET|PASSWORD)\b[\"']?\s*[:=]\s*[\"']?"
    r"[^\s\"',}]{8,}"
)
_MIN_SESSION_DIGITS = 6


class SweepError(Exception):
    """A source the sweep needs is missing or unreadable: the sweep fails closed."""


@dataclass
class Failure:
    check: int
    where: str
    message: str

    def __str__(self) -> str:
        return f"check {self.check} ({CHECK_NAMES[self.check]}): {self.where}: {self.message}"


CHECK_NAMES = {
    1: "leak lint",
    2: "tooling words",
    3: "banned phrases",
    4: "numbers",
    5: "models and racing",
    6: "images",
    7: "secrets",
}


# ---------------------------------------------------------------- the stamp key


def _is_stamp(name: str) -> bool:
    return name.startswith(STAMP_PREFIX) and name.endswith(STAMP_SUFFIX)


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tree_sha256(root: Path, skip: Path | None = None) -> str:
    """sha256 over sorted `<relpath>\\t<file sha256>\\n` lines, stamps and `skip` left out."""
    lines: list[str] = []
    skip_resolved = skip.resolve() if skip is not None else None
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _is_stamp(path.name):
            continue
        if skip_resolved is not None and path.resolve().is_relative_to(skip_resolved):
            continue
        rel = path.relative_to(root).as_posix()
        lines.append(f"{rel}\t{_file_sha(path)}\n")
    lines.sort()
    return hashlib.sha256("".join(lines).encode("utf-8")).hexdigest()


def bundle_sha256(bundle: Path) -> str:
    """The stamp key: sha256 over the bundle's sorted `<relpath>\\t<sha256>\\n` lines.

    relpath uses forward slashes, relative to `bundle`; every `.sweep-*.ok` stamp is left out.
    """
    return tree_sha256(bundle)


def stamp_path(bundle: Path) -> Path:
    return bundle / f"{STAMP_PREFIX}{bundle_sha256(bundle)}{STAMP_SUFFIX}"


# ---------------------------------------------------------------- served files


@dataclass
class Served:
    path: Path
    rel: str
    text: str | None  # None for a binary file


def _decode(data: bytes) -> str | None:
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def served_files(page: Path, bundle: Path) -> list[Served]:
    seen: dict[Path, Served] = {}
    for root in (page, bundle):
        for path in sorted(root.rglob("*")):
            if not path.is_file() or _is_stamp(path.name):
                continue
            key = path.resolve()
            if key in seen:
                continue
            rel = path.relative_to(page if key.is_relative_to(page.resolve()) else bundle)
            seen[key] = Served(path, rel.as_posix(), _decode(path.read_bytes()))
    return sorted(seen.values(), key=lambda s: s.rel)


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


# ---------------------------------------------------------------- names


@dataclass
class Names:
    names: list[str]
    league: list[str]
    racing_ids: list[str] = field(default_factory=list)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SweepError(
            f"{path}: cannot be read ({exc.strerror or type(exc).__name__})."
        ) from None
    except json.JSONDecodeError:
        raise SweepError(f"{path}: not JSON.") from None


def _racing_ids(names_dir: Path) -> list[str]:
    """Sim session numbers, customer ids, stream file names: none may reach a served file."""
    ids: set[str] = set()
    league = _read_json(names_dir / "league.json")
    if not isinstance(league, dict) or not isinstance(league.get("sessions"), dict):
        raise SweepError(f"{names_dir / 'league.json'}: no sessions object.")
    for key, entry in league["sessions"].items():
        head = str(key).split("/", 1)[0]
        if head.isdigit():
            ids.add(head)
        if isinstance(entry, dict):
            sub = entry.get("subsession")
            if isinstance(sub, (str, int)) and str(sub).isdigit():
                ids.add(str(sub))
            stream = entry.get("stream")
            if isinstance(stream, str) and stream:
                ids.update(_file_name_ids(Path(stream).name))
    number_map = league.get("number_map")
    entries = number_map.get("entries") if isinstance(number_map, dict) else None
    for item in entries or []:
        if not isinstance(item, dict):
            continue
        cust = item.get("cust_id")
        if isinstance(cust, (str, int)) and str(cust).strip():
            ids.add(str(cust).strip())
        for sim_key in (item.get("sim_nums") or {}).keys():
            head = str(sim_key).split("/", 1)[0]
            if head.isdigit():
                ids.add(head)
    inputs = _read_json(names_dir / "inputs.json")
    replays = inputs.get("replays_dir") if isinstance(inputs, dict) else None
    if isinstance(replays, str) and replays:
        with contextlib.chdir(names_dir):
            folder = Path(replays).resolve()
        if folder.is_dir():
            for path in folder.iterdir():
                ids.update(_file_name_ids(path.name))
    return sorted(i for i in ids if i)


def _file_name_ids(name: str) -> set[str]:
    out = {name}
    stem = name
    while Path(stem).suffix:
        stem = Path(stem).stem
    out.add(stem)
    out.update(m for m in re.findall(r"\d+", name) if len(m) >= _MIN_SESSION_DIGITS)
    return out


def gather_names(names_dir: Path) -> Names:
    """Driver and league names the way `racing_card.py` gathers them, plus the racing ids."""
    if not names_dir.is_dir():
        raise SweepError(f"{names_dir}: the names source is missing; nothing can be checked.")
    for need in ("league.json", "inputs.json"):
        if not (names_dir / need).is_file():
            raise SweepError(f"{names_dir / need}: the names source is missing.")
    try:
        with contextlib.chdir(names_dir):  # relative feed and pack paths read from the folder
            names, league = card.gather_names(Path("."), None)
    except card.CardError as exc:
        raise SweepError(f"{names_dir}: {exc}") from None
    return Names(names=names, league=league, racing_ids=_racing_ids(names_dir))


# ---------------------------------------------------------------- checks


def _name_hits(text: str, names: list[str], banned: list[str]) -> int:
    """Count name and banned-phrase hits only (URLs, emails and handles are subtracted)."""
    every = Counter(lint.lint(text, names, banned, pitbot.ALLOW, paths=False))
    every.subtract(Counter(lint.lint(text, [], [], paths=False)))
    return sum(n for n in every.values() if n > 0)


def check_leaks(files: list[Served], names: Names) -> Iterator[Failure]:
    squashed_bans = [re.sub(r"\s+", "", b).casefold() for b in names.league]
    for f in files:
        for label, text in (("its path", f.rel), ("its text", f.text)):
            if text is None:
                continue
            hits = _name_hits(text, names.names, names.league)
            if hits:
                yield Failure(1, f.rel, f"{hits} driver or league name hit(s) in {label}")
            squashed = re.sub(r"\s+", "", text).casefold()
            if any(b and b in squashed for b in squashed_bans):
                yield Failure(1, f.rel, f"the league's name appears run together in {label}")
        if f.text is not None:
            for m in _EMAIL.finditer(f.text):
                yield Failure(1, f.rel, f"line {_line_of(f.text, m.start())}: an email address")


def check_tooling(files: list[Served]) -> Iterator[Failure]:
    for f in files:
        for m in _TOOLING.finditer(f.rel):
            yield Failure(2, f.rel, f"tooling word {m.group(0)!r} in its path")
        if f.text is None:
            continue
        for m in _TOOLING.finditer(f.text):
            line = _line_of(f.text, m.start())
            yield Failure(2, f.rel, f"line {line}: tooling word {m.group(0)!r}")


def banned_patterns() -> list[re.Pattern[str]]:
    """The medical and sports patterns, loaded from `tests/test_provenance.py` (one list)."""
    if not PROVENANCE_TEST.is_file():
        raise SweepError(f"{PROVENANCE_TEST}: the banned-phrase list is missing.")
    spec = importlib.util.spec_from_file_location("_faultline_provenance", PROVENANCE_TEST)
    if spec is None or spec.loader is None:
        raise SweepError(f"{PROVENANCE_TEST}: cannot be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.MEDICAL_PATTERNS) + list(module.SPORTS_PATTERNS)


def check_phrases(files: list[Served], patterns: list[re.Pattern[str]]) -> Iterator[Failure]:
    for f in files:
        if f.text is None:
            continue
        for pattern in patterns:
            for m in pattern.finditer(f.text):
                line = _line_of(f.text, m.start())
                yield Failure(3, f.rel, f"line {line}: banned phrase {m.group(0)!r}")


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[*`]", "", text).split())


def _readme_line(readme: list[str], number: Any) -> str | None:
    if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= len(readme):
        return None
    return readme[number - 1]


def check_numbers(
    bundle: Path, page_files: list[Served], readme: list[str], docs: dict[str, Any]
) -> Iterator[Failure]:
    cited: list[str] = []
    for doc_name, doc in docs.items():
        numbers = doc.get("numbers")
        if doc_name == "index.json" and not isinstance(numbers, dict):
            yield Failure(4, doc_name, "`numbers` is missing or not an object")
            continue
        for key, item in (numbers or {}).items():
            if not isinstance(item, dict) or not isinstance(item.get("text"), str):
                yield Failure(4, doc_name, f"numbers.{key}: no text")
                continue
            line = _readme_line(readme, item.get("readme_line"))
            if line is None:
                yield Failure(4, doc_name, f"numbers.{key}: readme_line is not a README line")
                continue
            cited.append(line)
            if _norm(item["text"]) not in _norm(line):
                yield Failure(
                    4,
                    doc_name,
                    f"numbers.{key}: {item['text']!r} is not on README line {item['readme_line']}",
                )
        for key in ("graded_replay", "shipped_replay"):
            if doc_name != "index.json":
                continue
            item = doc.get(key)
            if not isinstance(item, dict):
                yield Failure(4, doc_name, f"{key} is missing")
                continue
            line = _readme_line(readme, item.get("readme_line"))
            if line is None:
                yield Failure(4, doc_name, f"{key}: readme_line is not a README line")
                continue
            cited.append(line)
            sha = _HEX_PREFIX.match(str(item.get("sha256", "")).lower())
            if sha is None or sha.group(0) not in line.lower():
                yield Failure(
                    4, doc_name, f"{key}: the hash is not on README line {item['readme_line']}"
                )
    allowed = {m.group(0) for line in cited for m in _NUMBER.finditer(_norm(line))}
    for f in page_files:
        if f.text is None or not f.rel.lower().endswith((".html", ".htm")):
            continue
        text = card.visible_text(f.text)
        for model in REQUIRED_MODELS:
            text = text.replace(model, " ")
        for m in _NUMBER.finditer(text):
            if m.group(0) not in allowed:
                yield Failure(4, f.rel, f"the number {m.group(0)!r} is on no cited README line")


def _words_blocks(clip: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    for i, ruling in enumerate(clip.get("rulings") or []):
        if not isinstance(ruling, dict):
            continue
        words = ruling.get("words")
        if words is None:
            continue
        if not isinstance(words, dict):
            yield f"rulings[{i}].words", words
            continue
        for key, block in words.items():
            if block is not None:
                yield f"rulings[{i}].words.{key}", block


def _named(block: Any) -> bool:
    return isinstance(block, dict) and isinstance(block.get("model"), str) and bool(block["model"])


def check_models(
    files: list[Served], docs: dict[str, Any], clips: dict[str, Any], readme_text: str, names: Names
) -> Iterator[Failure]:
    index = docs["index.json"]
    if index.get("open_weight_line") != OPEN_WEIGHT_LINE:
        yield Failure(5, "index.json", "the open-weight line is missing or not verbatim")
    if OPEN_WEIGHT_LINE not in readme_text:
        yield Failure(5, "README", "the open-weight line is no longer in the README")
    listed = {m.get("name") for m in index.get("models") or [] if isinstance(m, dict)}
    for model in REQUIRED_MODELS:
        if model not in listed:
            yield Failure(5, "index.json", f"{model!r} is not in the models list")
    for rel, clip in clips.items():
        for where, block in _words_blocks(clip):
            if not _named(block):
                yield Failure(5, rel, f"{where} does not name its model")
    racing = docs.get("racing.json")
    if racing is not None:
        for i, protest in enumerate(racing.get("protests") or []):
            for j, read in enumerate((protest or {}).get("reads") or []):
                if not _named(read):
                    yield Failure(5, "racing.json", f"protests[{i}].reads[{j}] names no model")
    for f in files:
        for label, text in (("its path", f.rel), ("its text", f.text)):
            if text is None:
                continue
            hits = _name_hits(text, [], names.racing_ids)
            if hits:
                yield Failure(
                    5, f.rel, f"{hits} session number, customer id or stream name(s) in {label}"
                )
        if _is_image(f) and "racing" in f.rel.casefold():
            yield Failure(5, f.rel, "a racing image is served")


def _is_image(f: Served) -> bool:
    suffix = f.path.suffix.lower()
    if suffix in RASTER_SUFFIXES or suffix == ".svg":
        return True
    if f.text is None:
        head = f.path.read_bytes()[:8]
        return any(head.startswith(m) for m in _RASTER_MAGIC)
    return False


def _entries(doc: Any) -> list[Any]:
    if isinstance(doc, dict) and isinstance(doc.get("frames"), list):
        return list(doc["frames"])
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):  # {file: {...}} or {file: bool}
        return [
            {"file": k, **(v if isinstance(v, dict) else {"checked": v})} for k, v in doc.items()
        ]
    return []


def _resolve(file: str, frames_dir: Path, bundle: Path) -> Path | None:
    for base in (frames_dir, bundle, frames_dir.parent):
        candidate = (base / file).resolve()
        if candidate.is_file():
            return candidate
    return None


def check_images(files: list[Served], bundle: Path, index: dict[str, Any]) -> Iterator[Failure]:
    clips = {c.get("id"): c for c in index.get("clips") or [] if isinstance(c, dict)}
    real = {cid for cid, c in clips.items() if c.get("kind") == "real"}
    images = [f for f in files if _is_image(f) and f.path.suffix.lower() != ".svg"]
    frames_dir = bundle / "frames"
    manifest_path = frames_dir / "frames.json"
    if not manifest_path.is_file():
        if images:
            yield Failure(6, "frames/frames.json", "missing, so no image can be accounted for")
        return
    try:
        manifest = _entries(_read_json(manifest_path))
    except SweepError as exc:
        yield Failure(6, "frames/frames.json", str(exc))
        return
    listed: dict[Path, dict[str, Any]] = {}
    for i, entry in enumerate(manifest):
        if not isinstance(entry, dict) or not isinstance(entry.get("file"), str):
            yield Failure(6, "frames/frames.json", f"entry {i} names no file")
            continue
        where = _resolve(entry["file"], frames_dir, bundle)
        if where is not None:
            listed[where] = entry
    blurred: dict[Path, Any] = {}
    blurred_path = frames_dir / "blurred.json"
    if blurred_path.is_file():
        try:
            for entry in _entries(_read_json(blurred_path)):
                if isinstance(entry, dict) and isinstance(entry.get("file"), str):
                    where = _resolve(entry["file"], frames_dir, bundle)
                    if where is not None:
                        blurred[where] = entry.get("checked")
        except SweepError as exc:
            yield Failure(6, "frames/blurred.json", str(exc))
    for f in images:
        key = f.path.resolve()
        entry = listed.get(key)
        if entry is None:
            yield Failure(6, f.rel, "an image not listed in the frames manifest")
            continue
        if entry.get("sha256") != _file_sha(f.path):
            yield Failure(6, f.rel, "its sha256 differs from the frames manifest")
        clip = entry.get("clip")
        if clip not in clips:
            yield Failure(6, f.rel, "its clip is not in the forklift clip list")
        elif clip in real and blurred.get(key) is not True:
            yield Failure(6, f.rel, "a real-footage frame without `checked: true` in blurred.json")


def _scan_root_ok(folder: Path) -> str | None:
    resolved = folder.resolve()
    if (resolved / ".git").exists() or (resolved / "workspaces").exists():
        return f"{folder}: holds a repo or the workspaces folder; refused, scan the bundle only."
    if REPO.resolve().is_relative_to(resolved):
        return f"{folder}: holds the whole repo; refused, scan the bundle only."
    return None


def run_gitleaks(folder: Path, gitleaks: str) -> list[str]:
    """Problems found by `gitleaks dir` on `folder`: [] when clean. Raises SweepError if absent."""
    exe = shutil.which(gitleaks)
    if exe is None:
        raise SweepError(
            f"gitleaks ({gitleaks}) is not installed, so the secret scan cannot run; no stamp. "
            "Install gitleaks and run the sweep again."
        )
    refused = _scan_root_ok(folder)
    if refused:
        return [refused]
    with tempfile.TemporaryDirectory() as tmp:
        report = Path(tmp) / "report.json"
        done = subprocess.run(
            [
                exe,
                "dir",
                str(folder),
                "--no-banner",
                "--redact",
                "--exit-code",
                "1",
                "--report-format",
                "json",
                "--report-path",
                str(report),
                "--log-level",
                "error",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if done.returncode == 0:
            return []
        if done.returncode == 1 and report.is_file():
            try:
                found = json.loads(report.read_text(encoding="utf-8") or "[]")
            except json.JSONDecodeError:
                found = []
            out = [
                f"{Path(str(hit.get('File', '?'))).name}: gitleaks rule {hit.get('RuleID', '?')}"
                for hit in found
                if isinstance(hit, dict)
            ]
            return out or ["gitleaks reported a leak"]
        return [f"gitleaks failed (exit {done.returncode}); the scan did not run"]


def check_secrets(
    files: list[Served], page: Path, bundle: Path, gitleaks: str
) -> Iterator[Failure]:
    for f in files:
        name = f.path.name.casefold()
        if name == ".env" or name.startswith(".env.") or name.endswith(".env"):
            yield Failure(7, f.rel, "a .env file is served")
        if f.text is not None:
            for m in _KEY_VALUE.finditer(f.text):
                yield Failure(7, f.rel, f"line {_line_of(f.text, m.start())}: a key with a value")
    roots = [page]
    if not bundle.resolve().is_relative_to(page.resolve()):
        roots.append(bundle)
    for root in roots:
        for problem in run_gitleaks(root, gitleaks):
            yield Failure(7, root.name or str(root), problem)


# ---------------------------------------------------------------- the sweep


def _load_docs(bundle: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    docs: dict[str, Any] = {}
    index_path = bundle / "index.json"
    if not index_path.is_file():
        raise SweepError(f"{index_path}: the bundle has no index.json.")
    docs["index.json"] = _read_json(index_path)
    if not isinstance(docs["index.json"], dict):
        raise SweepError(f"{index_path}: not a JSON object.")
    racing = bundle / "racing.json"
    if not racing.is_file():
        raise SweepError(f"{racing}: the bundle has no racing.json; the racing data was not built.")
    docs["racing.json"] = _read_json(racing)
    if not isinstance(docs["racing.json"], dict):
        raise SweepError(f"{racing}: not a JSON object.")
    clips: dict[str, Any] = {}
    for path in sorted((bundle / "clips").glob("*.json")):
        clip = _read_json(path)
        if not isinstance(clip, dict):
            raise SweepError(f"{path}: not a JSON object.")
        clips[path.relative_to(bundle).as_posix()] = clip
    return docs, clips


def sweep(
    bundle: Path,
    page: Path,
    names_dir: Path,
    readme: Path = REPO / "README.md",
    gitleaks: str = "gitleaks",
) -> list[Failure]:
    """Run the seven checks; return every failure. Raises SweepError when a source is missing."""
    for folder, label in ((bundle, "--bundle"), (page, "--page")):
        if not folder.is_dir():
            raise SweepError(f"{folder}: {label} is not a folder.")
    if not readme.is_file():
        raise SweepError(f"{readme}: the README is missing.")
    names = gather_names(names_dir)
    patterns = banned_patterns()
    readme_text = readme.read_text(encoding="utf-8")
    readme_lines = readme_text.splitlines()
    docs, clips = _load_docs(bundle)
    files = served_files(page, bundle)
    page_files = [f for f in files if f.path.resolve().is_relative_to(page.resolve())]
    failures: list[Failure] = []
    failures += check_leaks(files, names)
    failures += check_tooling(files)
    failures += check_phrases(files, patterns)
    failures += check_numbers(bundle, page_files, readme_lines, docs)
    failures += check_models(files, docs, clips, readme_text, names)
    failures += check_images(files, bundle, docs["index.json"])
    for f in files:
        suffix = f.path.suffix.lower()
        if f.text is None and not _is_image(f):
            failures.append(Failure(6, f.rel, "a binary file that is not an image"))
        elif f.text is None and suffix in TEXT_SUFFIXES:
            failures.append(Failure(6, f.rel, "a text-type file that is not UTF-8 text"))
    failures += check_secrets(files, page, bundle, gitleaks)
    return failures


def write_stamp(bundle: Path, page: Path) -> Path:
    stamp = stamp_path(bundle)
    body = {
        "bundle_sha256": bundle_sha256(bundle),
        "page_sha256": tree_sha256(page, skip=bundle),
        "checks": [CHECK_NAMES[n] for n in sorted(CHECK_NAMES)],
    }
    stamp.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    return stamp


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bundle", type=Path, required=True, help="the built bundle (site/data)")
    parser.add_argument("--page", type=Path, required=True, help="the page folder (site)")
    parser.add_argument("--names", type=Path, required=True, help="the racing names folder")
    parser.add_argument("--readme", type=Path, default=REPO / "README.md")
    parser.add_argument("--gitleaks", default="gitleaks", help="the gitleaks command")
    args = parser.parse_args(list(argv) if argv is not None else None)
    old = None
    try:
        if args.bundle.is_dir():
            old = stamp_path(args.bundle)
        failures = sweep(args.bundle, args.page, args.names, args.readme, args.gitleaks)
    except SweepError as exc:
        if old is not None and old.is_file():
            old.unlink()
        print(f"site sweep refused: {exc}", file=sys.stderr)
        print("No stamp written.", file=sys.stderr)
        return 2
    for number in sorted(CHECK_NAMES):
        mine = [f for f in failures if f.check == number]
        verdict = "pass" if not mine else f"{len(mine)} failure(s)"
        print(f"{number} {CHECK_NAMES[number]}: {verdict}")
        for failure in mine:
            print(f"  {failure.where}: {failure.message}")
    if failures:
        if old is not None and old.is_file():
            old.unlink()
        print("No stamp written.")
        return 1
    print(f"All seven checks pass. Stamp written: {write_stamp(args.bundle, args.page)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
