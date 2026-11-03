"""The hygiene sweep over every file the live page serves; writes a stamp only when all pass.

    uv run python scripts/site_sweep.py --bundle site/data --page site --names data/racing

Seven checks, each over every served file (the page folder and the bundle folder):

1. Leak lint (`faultline.lint`): no driver name and no league name. The names are gathered the
   way `scripts/racing_card.py` gathers them from the racing names folder (`league.json` and
   its feeds, `inputs.json` and its pack). A missing or unreadable names source fails closed.
2. Tooling words: none of `TOOLING_WORDS`, case-insensitive, whole word.

Checks 1 and 2 read each file's prose view (`prose_view`): the file as served, with only the
language's own markup words blanked, so a standard HTML element name (`<main>`) or a CSS
property name (`cursor:`) is not read as a name or a tooling word. Both lists are closed:
an HTML name is blanked only in a real tag opening (`<name` or `</name` followed by
whitespace, `>` or `/`), never inside a quoted attribute value, a comment or a raw-text
body (`script`, `style`, `textarea`, `title`); a CSS name is blanked only when it is a
property in `CSS_PROPERTIES`, in declaration position (right after `{` or `;`), outside a
comment or a quoted string. Everything else stays in, and every byte of every other file.
3. Banned phrases: the medical and sports patterns of `tests/test_provenance.py`.
4. Numbers: every entry of `numbers` in `index.json` and in `racing.json` (both required) appears on
   its cited README line, the replay hashes sit on theirs, each replay's `lines` count is stated
   (in digits or as a word) on its hash line, or, when the hash sits in a code block, on the
   prose line that introduces the block (`replay_count_line`), and every number in the page's
   HTML text appears on one of those cited lines.
5. Models: every `words` block and every racing read names its model; the open-weight line is
   verbatim; the four Meta models are in the models list. Racing: no sim session number,
   customer id, stream name or league folder name in any served file, and no racing image.
6. Images: every image is listed in the frames manifest (`frames/frames.json`) with its hash,
   belongs to a clip in `index.json` or is a demo-shift window's frame (named by a `shift.json`
   window, under `frames/`, in a `wNN-` folder named by that window's own `window` id), and
   every real-footage frame has `checked: true` in `frames/blurred.json`. A window frame counts
   as synthetic only when the shift run's own record (`windows.jsonl` in the folder that
   `sources.json` names as `shift.output.path`, never served) holds that window with the same
   entry, record and clip, read from a clip file inside a `synthetic` folder. Anything less,
   including a missing record, treats the frame as real footage: it needs its blur check.
   Nothing served (`frames.json`'s `kind`, `shift.json`) can vouch for itself.
   Videos (`VIDEO_SUFFIXES`), failing closed: every one is listed in `video/videos.json` (and
   sits in `video/`) with a matching sha256, is named `<window id>.mp4` by its manifest window,
   that window is in `shift.json` with the same clip and is `_proven_synthetic` on the shift
   record, neither its clip nor the record's is in `index.json`'s real group, and ffprobe shows
   exactly one stream, a video one (no audio). No ffprobe on PATH is a failure, never a pass. A
   manifest entry whose file is not there fails too.
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
VIDEO_SUFFIXES = {".mp4", ".m4v", ".webm", ".mov", ".mkv"}
_RASTER_MAGIC = (b"\xff\xd8\xff", b"\x89PNG", b"GIF8", b"RIFF", b"BM", b"\x00\x00\x01\x00")

_NUMBER = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w])")
_HEX_PREFIX = re.compile(r"^[0-9a-f]{8,64}")
_EMAIL = re.compile(r"(?<![\w.+\-])[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_KEY_VALUE = re.compile(
    r"\b[A-Z][A-Z0-9_]*(?:API_KEY|_KEY|_TOKEN|_SECRET|PASSWORD)\b[\"']?\s*[:=]\s*[\"']?"
    r"[^\s\"',}]{8,}"
)
_MIN_SESSION_DIGITS = 6

# The language's own words, blanked by `prose_view`: the standard HTML and SVG element names.
# A custom element (`<x-name>`) or any other tag name is not in this set and stays checked.
HTML_ELEMENTS = frozenset(
    """
    a abbr address area article aside audio b base bdi bdo blockquote body br button canvas
    caption cite code col colgroup data datalist dd del details dfn dialog div dl dt em embed
    fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header hgroup hr html i iframe
    img input ins kbd label legend li link main map mark menu meta meter nav noscript object ol
    optgroup option output p picture pre progress q rp rt ruby s samp script search section
    select slot small source span strong style sub summary sup table tbody td template textarea
    tfoot th thead time title tr track u ul var video wbr
    svg g path circle ellipse line polyline polygon rect text tspan defs desc symbol use
    clippath lineargradient radialgradient stop mask pattern marker
    """.split()
)
# A real tag opening: `<name` or `</name`, ended by whitespace, `>` or `/`.
_HTML_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)(?=[\s>/])")
# Elements whose body is raw text: no tag inside them is markup until their own end tag.
_HTML_RAW = frozenset({"script", "style", "textarea", "title"})
# The language's own words in CSS, blanked by `prose_view`: real property names only.
# An unknown word before `:` (a selector, a value, a custom property) stays checked.
CSS_PROPERTIES = frozenset(
    """
    accent-color align-content align-items align-self all animation animation-delay
    animation-direction animation-duration animation-fill-mode animation-iteration-count
    animation-name animation-play-state animation-timing-function appearance aspect-ratio
    backdrop-filter backface-visibility background background-attachment background-blend-mode
    background-clip background-color background-image background-origin background-position
    background-repeat background-size block-size border border-block border-bottom
    border-bottom-color border-bottom-left-radius border-bottom-right-radius border-bottom-style
    border-bottom-width border-collapse border-color border-image border-inline border-left
    border-left-color border-left-style border-left-width border-radius border-right
    border-right-color border-right-style border-right-width border-spacing border-style
    border-top border-top-color border-top-left-radius border-top-right-radius border-top-style
    border-top-width border-width bottom box-shadow box-sizing break-inside caption-side
    caret-color clear clip clip-path color color-scheme column-count column-gap columns contain
    container content content-visibility counter-increment counter-reset cursor direction
    display empty-cells fill fill-opacity filter flex flex-basis flex-direction flex-flow
    flex-grow flex-shrink flex-wrap float font font-family font-feature-settings font-kerning
    font-size font-stretch font-style font-variant font-variant-numeric font-weight gap grid
    grid-area grid-auto-columns grid-auto-flow grid-auto-rows grid-column grid-column-end
    grid-column-start grid-row grid-row-end grid-row-start grid-template grid-template-areas
    grid-template-columns grid-template-rows height hyphens image-rendering inline-size inset
    isolation justify-content justify-items justify-self left letter-spacing line-height
    list-style list-style-position list-style-type margin margin-block margin-bottom
    margin-inline margin-left margin-right margin-top mask max-block-size max-height
    max-inline-size max-width min-block-size min-height min-inline-size min-width mix-blend-mode
    object-fit object-position opacity order outline outline-color outline-offset outline-style
    outline-width overflow overflow-anchor overflow-wrap overflow-x overflow-y overscroll-behavior
    padding padding-block padding-bottom padding-inline padding-left padding-right padding-top
    place-content place-items place-self pointer-events position quotes resize right rotate row-gap
    scale scroll-behavior scroll-margin scroll-margin-top scroll-padding scroll-snap-align
    scroll-snap-type scrollbar-color scrollbar-gutter scrollbar-width shape-rendering stroke
    stroke-dasharray stroke-dashoffset stroke-linecap stroke-linejoin stroke-opacity stroke-width
    tab-size table-layout text-align text-anchor text-decoration text-decoration-color
    text-decoration-line text-decoration-style text-decoration-thickness text-indent
    text-overflow text-rendering text-shadow text-size-adjust text-transform
    text-underline-offset text-wrap top touch-action transform transform-origin transition
    transition-delay transition-duration transition-property transition-timing-function
    translate unicode-bidi user-select vector-effect vertical-align visibility white-space
    width will-change word-break word-spacing word-wrap writing-mode z-index
    -webkit-backdrop-filter -webkit-font-smoothing -webkit-overflow-scrolling
    -webkit-tap-highlight-color -webkit-text-size-adjust -webkit-appearance
    -moz-osx-font-smoothing
    """.split()
)
# CSS: a comment or a quoted string is kept whole, and an unterminated string is not a string.
_CSS_KEEP = re.compile(r"""/\*.*?\*/|"(?:[^"\\\n]|\\.)*"|'(?:[^'\\\n]|\\.)*'""", re.DOTALL)
# Declaration position: right after `{` or `;` (whitespace allowed), a name, then `:`.
_CSS_DECLARATION = re.compile(r"([{;]\s*)(-?[A-Za-z][A-Za-z0-9-]*)(\s*:)")
_WINDOW_FOLDER = re.compile(r"^w\d+-")
NUMBER_WORDS = {
    word: n
    for n, word in enumerate(
        """zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen
        fifteen sixteen seventeen eighteen nineteen twenty""".split()
    )
}
DEFAULT_SOURCES = REPO / "data" / "site" / "sources.json"


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


# ---------------------------------------------------------------- the prose view


def _blank(text: str, start: int, end: int) -> str:
    return text[:start] + " " * (end - start) + text[end:]


def _html_prose(text: str) -> str:
    """Blank the standard element names of real tag openings only.

    Comments, quoted attribute values and raw-text bodies are stepped over whole, so a
    `<name` inside any of them is never blanked.
    """
    out = text
    n = len(text)
    i = 0
    while True:
        j = text.find("<", i)
        if j < 0:
            break
        if text.startswith("<!--", j):
            end = text.find("-->", j + 4)
            i = n if end < 0 else end + 3
            continue
        m = _HTML_TAG.match(text, j)
        if m is None:
            i = j + 1
            continue
        name = m.group(2).casefold()
        if name in HTML_ELEMENTS:
            out = _blank(out, m.start(2), m.end(2))
        k = m.end()
        while k < n and text[k] != ">":  # the attributes, quoted values stepped over whole
            if text[k] in "\"'":
                close = text.find(text[k], k + 1)
                k = n if close < 0 else close + 1
            else:
                k += 1
        i = k + 1
        if not m.group(1) and name in _HTML_RAW:
            end = re.compile(rf"</{name}(?=[\s>/])", re.IGNORECASE).search(text, i)
            i = n if end is None else end.start()
    return out


def _css_names(segment: str) -> str:
    def blank(m: re.Match[str]) -> str:
        if m.group(2).casefold() not in CSS_PROPERTIES:
            return m.group(0)
        return m.group(1) + " " * len(m.group(2)) + m.group(3)

    return _CSS_DECLARATION.sub(blank, segment)


def _css_prose(text: str) -> str:
    out: list[str] = []
    pos = 0
    for m in _CSS_KEEP.finditer(text):
        out.append(_css_names(text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_css_names(text[pos:]))
    return "".join(out)


def prose_view(f: Served) -> str | None:
    """The file's text with its language's own markup words blanked (same length, same lines).

    `.html`/`.htm`: standard element names in real tag openings. `.css`: real property names
    in declaration position.
    Any other file is returned whole.
    """
    if f.text is None:
        return None
    suffix = f.path.suffix.lower()
    if suffix in {".html", ".htm"}:
        return _html_prose(f.text)
    if suffix == ".css":
        return _css_prose(f.text)
    return f.text


# ---------------------------------------------------------------- checks


def _name_hits(text: str, names: list[str], banned: list[str]) -> int:
    """Count name and banned-phrase hits only (URLs, emails and handles are subtracted)."""
    every = Counter(lint.lint(text, names, banned, pitbot.ALLOW, paths=False))
    every.subtract(Counter(lint.lint(text, [], [], paths=False)))
    return sum(n for n in every.values() if n > 0)


def check_leaks(files: list[Served], names: Names) -> Iterator[Failure]:
    squashed_bans = [re.sub(r"\s+", "", b).casefold() for b in names.league]
    for f in files:
        for label, text, prose in (
            ("its path", f.rel, f.rel),
            ("its text", f.text, prose_view(f)),
        ):
            if text is None or prose is None:
                continue
            hits = _name_hits(prose, names.names, names.league)
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
        prose = prose_view(f)
        if prose is None:
            continue
        for m in _TOOLING.finditer(prose):
            line = _line_of(prose, m.start())
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


def _states_count(line: str, count: int) -> bool:
    if any(m.group(0) == str(count) for m in _NUMBER.finditer(_norm(line))):
        return True
    words = re.findall(r"[a-z]+", line.casefold())
    return any(NUMBER_WORDS.get(w) == count for w in words)


def replay_count_line(readme: list[str], number: int, count: int) -> int | None:
    """The README line (1-based) that states a replay's line count, or None.

    The count is read from the hash's own line; when that line sits inside a fenced code
    block, it is read from the prose line that introduces the block instead (the nearest
    non-blank line above the opening fence), never from another code line.
    """
    if not 1 <= number <= len(readme):
        return None
    fences = [i for i in range(number - 1) if readme[i].lstrip().startswith("```")]
    where = number
    if len(fences) % 2:  # inside a code block: its opening fence is the last one above
        k = fences[-1] - 1
        while k >= 0 and not readme[k].strip():
            k -= 1
        if k < 0:
            return None
        where = k + 1
    return where if _states_count(readme[where - 1], count) else None


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
            count = item.get("lines")
            stated = (
                replay_count_line(readme, item["readme_line"], count)
                if isinstance(count, int) and not isinstance(count, bool)
                else None
            )
            if stated is None:
                yield Failure(
                    4,
                    doc_name,
                    f"{key}: lines {count!r} is not stated on README line {item['readme_line']} "
                    "or on the line that introduces its code block",
                )
            else:
                cited.append(readme[stated - 1])
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


def _window_files(shift: Any, frames_dir: Path, bundle: Path) -> dict[Path, dict[str, Any]]:
    """Each frame file a demo-shift window names -> that window (its `shift.json` object).

    Only a file under `frames/`, whose folder is the window's own `window` id and starts
    `wNN-`, counts; the frames manifest must give that same id as the frame's clip.
    """
    out: dict[Path, dict[str, Any]] = {}
    root = frames_dir.resolve()
    windows = shift.get("windows") if isinstance(shift, dict) else None
    for window in windows or []:
        if not isinstance(window, dict):
            continue
        wid = window.get("window")
        if not isinstance(wid, str) or not _WINDOW_FOLDER.match(wid):
            continue
        if not isinstance(window.get("clip"), str):
            continue
        named = [window.get("poster")]
        for ruling in window.get("rulings") or []:
            for frame in (ruling or {}).get("frames") or []:
                if isinstance(frame, dict):
                    named.append(frame.get("src"))
        for file in named:
            if not isinstance(file, str):
                continue
            where = _resolve(file, frames_dir, bundle)
            if where is None or not where.is_relative_to(root) or where.parent.name != wid:
                continue
            out[where] = window
    return out


def shift_record(sources: Path | None) -> dict[str, dict[str, Any]]:
    """The shift run's own windows (`windows.jsonl`), by window id; {} when there is none.

    It is read from the folder `sources.json` names as `shift.output.path` (server only,
    never served), so it is a witness the served files cannot write for themselves.
    """
    if sources is None:
        return {}
    doc = _read_json(sources)
    folder = (
        ((doc.get("shift") or {}).get("output") or {}).get("path")
        if isinstance(doc, dict)
        else None
    )
    if not isinstance(folder, str) or not folder:
        return {}
    path = Path(folder)
    if not path.is_absolute():
        path = sources.parent / path
    rows = path / "windows.jsonl"
    if not rows.is_file():
        return {}
    out: dict[str, dict[str, Any]] = {}
    for line in rows.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise SweepError(f"{rows}: a line is not JSON.") from None
        if isinstance(row, dict) and isinstance(row.get("window"), str):
            out[row["window"]] = row
    return out


def _proven_synthetic(window: dict[str, Any], record: dict[str, dict[str, Any]]) -> bool:
    """True only when the shift record shows this window read a clip from a synthetic folder."""
    row = record.get(window["window"])
    if row is None or not isinstance(row.get("clip"), str):
        return False
    clip = Path(row["clip"].replace("\\", "/"))
    return (
        row.get("entry") == window.get("entry")
        and row.get("record") == window.get("record")
        and clip.stem == window["clip"]
        and "synthetic" in (part.casefold() for part in clip.parts[:-1])
    )


def check_images(
    files: list[Served],
    bundle: Path,
    index: dict[str, Any],
    shift: Any = None,
    record: dict[str, dict[str, Any]] | None = None,
) -> Iterator[Failure]:
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
    windows = _window_files(shift, frames_dir, bundle)
    for f in images:
        key = f.path.resolve()
        entry = listed.get(key)
        if entry is None:
            yield Failure(6, f.rel, "an image not listed in the frames manifest")
            continue
        if entry.get("sha256") != _file_sha(f.path):
            yield Failure(6, f.rel, "its sha256 differs from the frames manifest")
        clip = entry.get("clip")
        window = windows.get(key)
        if clip in clips:
            is_real = clip in real
        elif window is not None and clip == window["window"]:
            # a demo-shift window's frame: synthetic only on the shift record's word, else real
            is_real = window["clip"] in real or not _proven_synthetic(window, record or {})
        else:
            yield Failure(6, f.rel, "its clip is not in the forklift clip list or the demo shift")
            continue
        if is_real and blurred.get(key) is not True:
            yield Failure(6, f.rel, "a real-footage frame without `checked: true` in blurred.json")


def _is_video(f: Served) -> bool:
    return f.path.suffix.lower() in VIDEO_SUFFIXES


def _video_streams(path: Path, ffprobe: str) -> list[str] | str:
    """The codec types of every stream in the file, or a problem in words."""
    exe = shutil.which(ffprobe)
    if exe is None:
        return f"ffprobe ({ffprobe}) is not installed, so the no-audio check cannot run"
    done = subprocess.run(
        [exe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        return f"ffprobe cannot read it (exit {done.returncode})"
    try:
        streams = json.loads(done.stdout or "{}").get("streams") or []
    except (json.JSONDecodeError, AttributeError):
        return "ffprobe gave no readable stream list"
    return [str((s or {}).get("codec_type")) for s in streams]


def check_videos(
    files: list[Served],
    bundle: Path,
    index: dict[str, Any],
    shift: Any = None,
    record: dict[str, dict[str, Any]] | None = None,
    ffprobe: str = "ffprobe",
) -> Iterator[Failure]:
    """Check 6 for videos: proven shift clips or hash-checked racing review replays, no audio."""
    videos = [f for f in files if _is_video(f)]
    video_dir = (bundle / "video").resolve()
    manifest_path = bundle / "video" / "videos.json"
    if not manifest_path.is_file():
        for f in videos:
            yield Failure(6, f.rel, "a video with no video/videos.json to list it")
        return
    try:
        doc = _read_json(manifest_path)
    except SweepError as exc:
        yield Failure(6, "video/videos.json", str(exc))
        return
    rows = doc.get("videos") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        yield Failure(6, "video/videos.json", "holds no `videos` list")
        return
    listed: dict[Path, dict[str, Any]] = {}
    for i, row in enumerate(rows):
        if not isinstance(row, dict) or not isinstance(row.get("file"), str):
            yield Failure(6, "video/videos.json", f"entry {i} names no file")
            continue
        where = (bundle / row["file"]).resolve()
        if not where.is_file():
            yield Failure(6, "video/videos.json", f"entry {i}: its file is not in the bundle")
            continue
        listed[where] = row
    clips = {c.get("id"): c for c in index.get("clips") or [] if isinstance(c, dict)}
    real = {cid for cid, c in clips.items() if c.get("kind") == "real" or c.get("group") == "real"}
    windows = {
        w["window"]: w
        for w in (shift.get("windows") if isinstance(shift, dict) else None) or []
        if isinstance(w, dict) and isinstance(w.get("window"), str)
    }
    racing = _read_json(bundle / "racing.json") if (bundle / "racing.json").is_file() else {}
    protests = {
        str(p.get("id")): p
        for p in (racing.get("protests") or [])
        if isinstance(p, dict) and p.get("id") is not None
    }
    for f in videos:
        key = f.path.resolve()
        row = listed.get(key)
        if row is None:
            yield Failure(6, f.rel, "a video not listed in video/videos.json")
            continue
        if not key.is_relative_to(video_dir):
            yield Failure(6, f.rel, "a video outside the bundle's video/ folder")
        if row.get("sha256") != _file_sha(f.path):
            yield Failure(6, f.rel, "its sha256 differs from video/videos.json")
        if row.get("kind") == "racing_review":
            pid = str(row.get("protest", ""))
            protest = protests.get(pid)
            source = REPO / "data/site/racing/preds-arm2.jsonl"
            source_frames = REPO / "data/site/racing/preds-arm2.jsonl.frames"
            source_row = None
            if source.is_file():
                try:
                    for line in source.read_text(encoding="utf-8").splitlines():
                        if not line:
                            continue
                        candidate = json.loads(line)
                        if str(candidate.get("id")) == pid:
                            source_row = candidate
                            break
                except (OSError, json.JSONDecodeError):
                    source_row = None
            hashes = row.get("source_sha256")
            expected = [x.get("sha256") for x in (source_row or {}).get("frames", [])]
            if not key.is_relative_to(video_dir) or key.name != f"racing-protest-{pid}.mp4":
                yield Failure(6, f.rel, "a racing replay outside its numbered video path")
            if protest is None or not isinstance(protest.get("frames_checked"), int):
                yield Failure(6, f.rel, "a racing replay with no reviewed protest record")
            if source_row is None or not isinstance(hashes, list) or hashes != expected:
                yield Failure(6, f.rel, "its source frames do not match the stored racing record")
            elif len(expected) != (protest or {}).get("frames_checked"):
                yield Failure(6, f.rel, "its frame count differs from the reviewed protest record")
            else:
                for digest in expected:
                    frame = source_frames / f"{digest}.jpg"
                    if not frame.is_file() or _file_sha(frame) != digest:
                        yield Failure(6, f.rel, "a source frame is missing or its hash changed")
                        break
            streams = _video_streams(f.path, ffprobe)
            if isinstance(streams, str):
                yield Failure(6, f.rel, streams)
            elif "audio" in streams:
                yield Failure(6, f.rel, "a video with an audio track")
            elif streams != ["video"]:
                yield Failure(6, f.rel, f"streams {streams}, not one video stream")
            continue
        wid = row.get("window")
        window = windows.get(wid) if isinstance(wid, str) else None
        if window is None or not _WINDOW_FOLDER.match(str(wid)):
            yield Failure(6, f.rel, "its window is not in the demo shift")
            continue
        if f.path.stem != wid:
            yield Failure(6, f.rel, "its file name is not its window's id")
        if row.get("clip") != window.get("clip"):
            yield Failure(6, f.rel, "its clip differs from the shift window's clip")
        rec_clip = ((record or {}).get(wid) or {}).get("clip")
        rec_stem = Path(rec_clip.replace("\\", "/")).stem if isinstance(rec_clip, str) else None
        if {row.get("clip"), window.get("clip"), rec_stem} & real:
            yield Failure(6, f.rel, "a video of a real-footage clip")
            continue
        if not isinstance(window.get("clip"), str) or not _proven_synthetic(window, record or {}):
            yield Failure(6, f.rel, "a video not proven synthetic by the shift record")
            continue
        streams = _video_streams(f.path, ffprobe)
        if isinstance(streams, str):
            yield Failure(6, f.rel, streams)
        elif "audio" in streams:
            yield Failure(6, f.rel, "a video with an audio track")
        elif streams != ["video"]:
            yield Failure(6, f.rel, f"streams {streams}, not one video stream")


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
    sources: Path | None = None,
    ffprobe: str = "ffprobe",
) -> list[Failure]:
    """Run the seven checks; return every failure. Raises SweepError when a source is missing.

    `sources` is the bundle's `sources.json`, read only for the shift run's record; without it
    every demo-shift window frame is held to the real-footage blur check.
    """
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
    shift_path = bundle / "shift.json"
    shift = _read_json(shift_path) if shift_path.is_file() else None
    record = shift_record(sources)
    failures += check_images(files, bundle, docs["index.json"], shift, record)
    failures += check_videos(files, bundle, docs["index.json"], shift, record, ffprobe)
    for f in files:
        suffix = f.path.suffix.lower()
        if _is_video(f):
            continue  # check_videos holds every video to its own proof
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
    parser.add_argument(
        "--sources",
        type=Path,
        default=None,
        help="the bundle's sources.json, for the shift run's record "
        f"(default {DEFAULT_SOURCES.relative_to(REPO).as_posix()} when present)",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.sources is None and DEFAULT_SOURCES.is_file():
        args.sources = DEFAULT_SOURCES
    old = None
    try:
        if args.bundle.is_dir():
            old = stamp_path(args.bundle)
        failures = sweep(
            args.bundle, args.page, args.names, args.readme, args.gitleaks, args.sources
        )
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
