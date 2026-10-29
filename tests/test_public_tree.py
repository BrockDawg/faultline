"""Invariant sweeps over every file git would publish: no driver name, no league name, no
private data, and a core that never reaches into an adapter.

The file set is `git ls-files --cached --others --exclude-standard`: what is committed plus
what the next commit could pick up. Ignored files (all of `data/`, `runs/`) are not in it.

The name and league checks are marked `private`: they read the league's own records in
memory, located the way `scripts/racing_prep.py` locates them (`data/racing/inputs.json`,
whose `incidents_tsv` and `pack_dir` name the decisions export and the rules pack, and
`data/racing/league.json`, whose sessions name each replay feed). On a clone `inputs.json`
is absent and they skip. Set `FAULTLINE_INPUTS` to point at another `inputs.json`.
A matched name or league name is never printed: a failure names the file and line only.

The file, extension and core checks need no private data and run everywhere. The banned
phrase sweep lives in `tests/test_provenance.py` and covers this file's text too.
"""

from __future__ import annotations

import ast
import gzip
import json
import os
import re
import subprocess
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

import pytest

from faultline.lint import name_tokens

REPO = Path(__file__).resolve().parent.parent
INPUTS = Path(os.environ.get("FAULTLINE_INPUTS") or REPO / "data" / "racing" / "inputs.json")

CORE_MODULES = ("record", "ledger", "lint", "client", "frames", "ruling", "cli", "roster")
CORE_WORDS = re.compile(r"\b(car|lap|incident)\b", re.IGNORECASE)
PRIVATE_SUFFIXES = (".mp4", ".jsonl", ".ndjson.gz", ".jpg")
_EDGE_L = r"(?<![^\W_])"  # not preceded by a letter or digit
_EDGE_R = r"(?![^\W_])"  # not followed by a letter or digit

# Common English words the sweep must not treat as name tokens. Each needs a reason; keep this
# set as short as possible. A full name holding one of these words is still caught as a phrase.
ALLOW: dict[str, str] = {
    "account": "a common English word, used in code and docs for a login or a record",
    "holder": "a common English word, as in place-holder and key holder",
    "main": "a common English word; also Python's entry point and git's default branch",
    "rose": "a common English word, the past tense of rise, as in a cost that rose",
}


# ---------------------------------------------------------------- the file set


def _repo_files() -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO), "ls-files", "--cached", "--others", "--exclude-standard"],
        capture_output=True,
        check=True,
    )
    names = result.stdout.decode("utf-8").splitlines()
    return [n for n in names if n and (REPO / n).is_file()]


def _commit_messages() -> list[tuple[str, str]]:
    """(short sha, full message) for every commit on the current branch."""
    result = subprocess.run(
        ["git", "-C", str(REPO), "log", "--format=%h%x1f%B%x1e"],
        capture_output=True,
        check=True,
    )
    out = []
    for rec in result.stdout.decode("utf-8", errors="replace").split("\x1e"):
        sha, _, body = rec.strip("\n").partition("\x1f")
        if sha:
            out.append((sha, body))
    return out


def _text_lines(name: str) -> Iterator[tuple[int, str]]:
    """Each line of a text file, numbered from 1; a binary or non-UTF-8 file yields nothing."""
    raw = (REPO / name).read_bytes()
    if b"\0" in raw:
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return
    yield from enumerate(text.splitlines(), start=1)


# ---------------------------------------------------------------- private sources (memory)


def _private_inputs() -> tuple[dict, dict]:
    """inputs.json and league.json, or a skip when the corpus is not on this machine."""
    if not INPUTS.is_file():
        pytest.skip(f"private corpus absent ({INPUTS.name} not found): name sweeps need it")
    league_path = INPUTS.parent / "league.json"
    if not league_path.is_file():
        pytest.skip("league.json absent: run scripts/racing_prep.py to build it first")
    inputs = json.loads(INPUTS.read_text(encoding="utf-8"))
    league = json.loads(league_path.read_text(encoding="utf-8"))
    return inputs, league


def _source(cfg: dict, key: str) -> Path:
    path = Path(cfg[key])
    assert path.exists(), f"inputs.json `{key}` points at a path that does not exist"
    return path


def _tsv_rows(path: Path) -> list[dict[str, str]]:
    """A tab export split on LF only (it is not quoted CSV), as dicts keyed by the header."""
    text = path.read_bytes().decode("utf-8", errors="replace")
    lines = [ln.rstrip("\r") for ln in text.split("\n") if ln.strip()]
    head = lines[0].split("\t")
    return [dict(zip(head, ln.split("\t"), strict=False)) for ln in lines[1:]]


def _clean(name: str | None) -> str:
    """A name with car numbers, NULLs and stray punctuation dropped, spaces collapsed."""
    if not name or name == "NULL":
        return ""
    name = name.replace("\\n", " ")
    name = re.sub(r"#\s*\d+|\b\d+\b", " ", name)
    name = re.sub(r"[^\w' .-]+", " ", name)
    return " ".join(name.split()).strip(" .-'")


def _driver_names(inputs: dict, league: dict) -> set[str]:
    names: set[str] = set()
    for feed in sorted({s["feed"] for s in league["sessions"].values()}):
        with gzip.open(feed, "rt", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                frame = json.loads(line)
                for item in (frame.get("rows") or []) + (frame.get("positions") or []):
                    names.add(_clean(item.get("name")))
    decisions = _source(inputs, "incidents_tsv")
    for row in _tsv_rows(decisions):
        names.add(_clean(row.get("reporter_name")))
        names.add(_clean(row.get("penalised")))
        for part in re.split(r"[;\n]|\\n|\band\b|&|,", row.get("involved") or ""):
            names.add(_clean(part))
    # The per-driver stats export sits beside the replays folder.
    stats = _source(inputs, "replays_dir").parent / "iracing_driver_stats.tsv"
    assert stats.is_file(), "iracing_driver_stats.tsv is missing beside the replays folder"
    for row in _tsv_rows(stats):
        names.add(_clean(row.get("name")))
    return {n for n in names if n}


def _name_patterns(names: set[str]) -> tuple[re.Pattern[str], re.Pattern[str] | None]:
    """Full names as phrases; every letter run over 3 letters as a whole word. Both ignore case.

    A word edge here is anything but a letter or digit, so `first_last` and `last.py` still hit.
    """
    phrases = sorted({n for n in names if " " in n}, key=len, reverse=True)
    full = re.compile(
        _EDGE_L
        + "("
        + "|".join(re.escape(p).replace(r"\ ", r"[\s_]+") for p in phrases)
        + ")"
        + _EDGE_R,
        re.IGNORECASE,
    )
    tokens = name_tokens(names, allow=ALLOW)
    if not tokens:
        return full, None
    alt = "|".join(sorted(map(re.escape, tokens), key=len, reverse=True))
    return full, re.compile(_EDGE_L + "(" + alt + ")" + _EDGE_R, re.IGNORECASE)


def _league_names(inputs: dict) -> set[str]:
    out: set[str] = set()
    pack_dir = _source(inputs, "pack_dir")
    out.add(pack_dir.name)
    pack_json = pack_dir / "pack.json"
    if pack_json.is_file():
        name = json.loads(pack_json.read_text(encoding="utf-8")).get("name") or ""
        if name:
            out.add(name)
    return {re.sub(r"\s+", "", n).casefold() for n in out if n}


# ---------------------------------------------------------------- 1, 2: names


def test_sweep_sees_this_file() -> None:
    assert "tests/test_public_tree.py" in _repo_files()


@pytest.mark.private
def test_no_driver_name_in_any_repo_file() -> None:
    inputs, league = _private_inputs()
    names = _driver_names(inputs, league)
    assert len(names) > 10, "the private sources yielded almost no names; the reader is broken"
    full, surname = _name_patterns(names)
    hits: list[str] = []
    for name in _repo_files():
        for no, line in _text_lines(name):
            if full.search(line) or (surname is not None and surname.search(line)):
                hits.append(f"{name}:{no}")
    for sha, body in _commit_messages():
        if full.search(body) or (surname is not None and surname.search(body)):
            hits.append(f"commit {sha}")
    assert not hits, "a driver name appears at: " + ", ".join(hits)


@pytest.mark.private
def test_no_league_name_in_any_repo_file() -> None:
    inputs, _ = _private_inputs()
    leagues = _league_names(inputs)
    assert leagues, "no league name could be read from the pack"
    hits: list[str] = []
    for name in _repo_files():
        for no, line in _text_lines(name):
            squashed = re.sub(r"\s+", "", line).casefold()
            if any(lg in squashed for lg in leagues):
                hits.append(f"{name}:{no}")
    for sha, body in _commit_messages():
        if any(lg in re.sub(r"\s+", "", body).casefold() for lg in leagues):
            hits.append(f"commit {sha}")
    assert not hits, "the league's name appears at: " + ", ".join(hits)


# ---------------------------------------------------------------- 3: private files


def test_no_data_path_is_tracked() -> None:
    bad = [n for n in _repo_files() if PurePosixPath(n).parts[0] == "data"]
    assert not bad, f"files under data/ would be published: {bad}"


def test_no_private_media_or_feed_outside_assets() -> None:
    bad = [
        n
        for n in _repo_files()
        if n.lower().endswith(PRIVATE_SUFFIXES) and PurePosixPath(n).parts[0] != "assets"
    ]
    assert not bad, f"video, feed, protest or frame files outside assets/: {bad}"


# ---------------------------------------------------------------- 4: one core, many adapters


def _core_paths() -> list[Path]:
    pkg = REPO / "src" / "faultline"
    return [pkg / f"{m}.py" for m in CORE_MODULES if (pkg / f"{m}.py").is_file()]


def _imports_adapter(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(a.name.split(".")[:2] == ["faultline", "adapters"] for a in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level == 0 and mod.split(".")[:2] == ["faultline", "adapters"]:
                return True
            if node.level == 1 and mod.split(".")[0] == "adapters":
                return True
            if node.level == 1 and not mod and any(a.name == "adapters" for a in node.names):
                return True
            if (
                node.level == 0
                and mod == "faultline"
                and any(a.name == "adapters" for a in node.names)
            ):
                return True
    return False


def test_core_never_imports_an_adapter() -> None:
    bad = [
        p.name
        for p in _core_paths()
        if _imports_adapter(ast.parse(p.read_text(encoding="utf-8"), filename=str(p)))
    ]
    assert not bad, f"core modules import an adapter: {bad}"


def test_core_has_no_racing_words() -> None:
    hits: list[str] = []
    for p in _core_paths():
        if p.stem == "cli":
            continue
        for no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if CORE_WORDS.search(line):
                hits.append(f"src/faultline/{p.name}:{no}")
    assert not hits, "racing words (car, lap, incident) in core: " + ", ".join(hits)


def test_adapter_import_detector() -> None:
    caught = (
        "import faultline.adapters.pitbot",
        "from faultline.adapters import pitbot",
        "from faultline.adapters.pitbot import feed",
        "from faultline import adapters",
        "from .adapters import pitbot",
        "from .adapters.pitbot import feed",
        "from . import adapters",
    )
    clean = ("import faultline.pack", "from .pack import load_pack", "from . import pack")
    for src in caught:
        assert _imports_adapter(ast.parse(src)), src
    for src in clean:
        assert not _imports_adapter(ast.parse(src)), src
