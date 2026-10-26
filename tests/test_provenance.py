"""Checks on PROVENANCE.md, README.md and the banned-phrase sweep over every repo text file."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parent.parent
PROVENANCE = REPO / "PROVENANCE.md"
README = REPO / "README.md"

PRE_EXISTING_HEADING = "## What existed before the hackathon"

ROUTER_SENTENCE = (
    "Pre-existing tooling I'd built, which already routed to Meta models. "
    "During the hackathon we extended it to:"
)

# The one regulation citation the section must carry; its part number reads like a year.
CFR_CITATION = "29 CFR 1910.178"

MONTHS = (
    "January February March April May June July August September October November December "
    "Jan Feb Mar Apr Jun Jul Aug Sep Sept Oct Nov Dec"
).split()
WEEKDAYS = (
    "Monday Tuesday Wednesday Thursday Friday Saturday Sunday Mon Tue Tues Wed Thu Thur Thurs Fri"
).split()

# Every banned literal is built by concatenation so this file never matches itself.
MEDICAL_PATTERNS = (
    re.compile("diag" + "nos", re.IGNORECASE),
    re.compile("treat" + "ment", re.IGNORECASE),
    re.compile("see a " + "doctor", re.IGNORECASE),
)
SPORTS_PATTERNS = (
    re.compile("co" + "ach", re.IGNORECASE),
    re.compile("ana" + r"ly[sz]e\s+(driver|performance)", re.IGNORECASE),
    re.compile("impr" + "ove your", re.IGNORECASE),
    re.compile("racecraft " + "analysis", re.IGNORECASE),
)


def _pre_existing_section() -> str:
    text = PROVENANCE.read_text(encoding="utf-8")
    start = text.index(PRE_EXISTING_HEADING)
    rest = text[start + len(PRE_EXISTING_HEADING) :]
    nxt = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: nxt.start()] if nxt else rest


def test_pre_existing_section_has_no_year() -> None:
    section = _pre_existing_section().replace(CFR_CITATION, "")
    assert not re.search(r"\b(19|20)\d{2}\b", section)


def test_pre_existing_section_has_no_numeric_day_and_month() -> None:
    assert not re.search(r"\d{1,2}[/-]\d{1,2}", _pre_existing_section())


def test_pre_existing_section_has_no_month_name() -> None:
    section = _pre_existing_section()
    found = [m for m in MONTHS if re.search(rf"\b{m}\b\.?", section)]
    assert found == []


def test_pre_existing_section_has_no_weekday_name() -> None:
    section = _pre_existing_section()
    found = [d for d in WEEKDAYS if re.search(rf"\b{d}\b", section)]
    assert found == []


def test_pre_existing_section_has_no_relative_day() -> None:
    section = _pre_existing_section().lower()
    assert "yesterday" not in section
    assert "the day before" not in section


def test_pre_existing_section_names_every_pre_existing_part() -> None:
    section = _pre_existing_section().lower()
    parts = [
        "PitBot",
        "telemetry",
        "video",
        "Rule Library",
        "forklift",
        "pack format",
        "tournament harness",
        "metering proxy",
        "task router",
    ]
    missing = [p for p in parts if p.lower() not in section]
    assert missing == []


def test_router_sentence_appears_verbatim_with_its_placeholder_line() -> None:
    lines = [line.strip() for line in _pre_existing_section().splitlines()]
    assert ROUTER_SENTENCE in lines
    after = lines[lines.index(ROUTER_SENTENCE) + 1]
    assert after == "- (filled in as work lands)"


def test_readme_links_provenance_and_build_log() -> None:
    text = README.read_text(encoding="utf-8")
    assert "](PROVENANCE.md)" in text
    assert "](BUILD_LOG.md)" in text


def _repo_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=REPO,
            capture_output=True,
            check=True,
        )
        names = result.stdout.decode("utf-8").splitlines()
        return [n for n in names if n and (REPO / n).is_file()]
    except (OSError, subprocess.CalledProcessError):
        skip = {".venv", ".git"}
        return [
            p.relative_to(REPO).as_posix()
            for p in REPO.rglob("*")
            if p.is_file() and not skip.intersection(p.relative_to(REPO).parts)
        ]


def _is_rule_text(name: str) -> bool:
    parts = PurePosixPath(name).parts
    return (
        len(parts) == 3 and parts[0] == "packs" and parts[2][:1].isdigit() and name.endswith(".md")
    )


def _read_text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\0" in data:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def test_sweep_finds_this_test_file_and_skips_the_venv() -> None:
    names = _repo_files()
    assert "tests/test_provenance.py" in names
    assert not any(n.startswith(".venv/") for n in names)


def test_no_repo_text_file_holds_a_banned_phrase() -> None:
    hits: list[str] = []
    for name in _repo_files():
        text = _read_text(REPO / name)
        if text is None:
            continue
        patterns = MEDICAL_PATTERNS
        if not _is_rule_text(name):
            patterns = patterns + SPORTS_PATTERNS
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                hits.append(f"{name}: {match.group(0)!r}")
    assert hits == []


def test_rule_text_is_exempt_from_sports_phrases_only() -> None:
    assert _is_rule_text("packs/oval/09-pit-road.md")
    assert not _is_rule_text("packs/README.md")
    assert not _is_rule_text("packs/oval/pack.json")
    assert not _is_rule_text("README.md")
