"""Leak lint: refuse outgoing text holding a person's name, a file path, a URL or a banned term.

Every prompt string and image name is checked before it leaves the machine. The lint is
domain-neutral: the caller hands it the names to refuse and any extra banned phrases (the
name of an event series or a site, for example). This module never reads a names list from disk.

Banned, all matched case-insensitively:

- each name in `names` as a whole phrase (its words may be split by any run of whitespace,
  line breaks included);
- each name token longer than 3 letters as a whole word (see `name_tokens`): a surname alone,
  in any case, glued to punctuation ("Ravelstone's", "(Ravelstone)") is a hit, but a token
  inside a longer word ("Ravelstones", "xRavelstone") is not;
- each phrase in `extra_banned`, matched the same way as a name phrase;
- file paths: a drive letter (`C:\\`, `d:/`), a run that starts with `/` or `\\` and a word, or
  a run of words joined by `/` or `\\`. Two short forms are exempt so units and fractions still
  read: a single separator between two runs of digits (`3/5`) or between two runs of at most
  2 letters (`m/s`, `km/h`). Prose like `and/or` is a hit: write "and" or "or" instead;
- file extensions such as `.mp4`, `.ndjson`, `.gz`, `.jsonl`, `.jpg` (see `_EXTENSIONS`);
- URLs: `scheme://...` and `www.` addresses;
- email addresses (`someone@example.org`), as one whole token;
- @handles (`@someone`), as one whole token; an `@` inside a word or an address is not a handle.

Per-person ids (a customer id, an account number, a user id) are not guessed by shape: the
caller passes each one in `extra_banned`, where it is matched as a whole word, so `4410273`
hits but `144102739` does not.

Name matching is strict on purpose, because outgoing prompts are prose written by code.
A real name token can also be a common English word ("main", "account"); a caller whose own
fixed text needs such a word passes it in `allow`, and that word is then never treated as a
name token (nor is a single-word name equal to it treated as a phrase). Allowing a word does
not allow a multi-word name that contains it: the full phrase is still refused.

`lint` returns every hit's matched text, ordered by character offset, then end offset.
`assert_clean` raises `LintError` on any hit; its message gives only the number of hits, their
kinds and their character offsets, never the matched text, so a refusal cannot itself leak.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

__all__ = ["LintError", "assert_clean", "lint", "name_tokens"]

_MIN_TOKEN_LETTERS = 4
_EXTENSIONS = (
    "avi",
    "csv",
    "gz",
    "jpeg",
    "jpg",
    "json",
    "jsonl",
    "mkv",
    "mov",
    "mp4",
    "ndjson",
    "png",
    "tsv",
    "webm",
    "zip",
)
_LETTER_RUN = re.compile(r"[^\W\d_]+")
_URL = re.compile(r"\b(?:[a-z][a-z0-9+.\-]*://|www\.)\S+", re.IGNORECASE)
_EMAIL = re.compile(r"(?<![\w.+\-])[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
_HANDLE = re.compile(r"(?<![\w.+\-@])@\w+")
_DRIVE = re.compile(r"(?<!\w)[a-z]:[\\/][\w.\-\\/]*", re.IGNORECASE)
_ROOTED = re.compile(r"(?<![\w.\-\\/:])[\\/]{1,2}\w[\w.\-\\/]*")
_JOINED = re.compile(r"(?<![\w.\-\\/:])[\w.\-]+(?:[\\/][\w.\-]+)+")
_EXTENSION = re.compile(r"\.(?:" + "|".join(_EXTENSIONS) + r")(?!\w)", re.IGNORECASE)
_SHORT_UNIT = re.compile(r"[^\W\d_]{1,2}[\\/][^\W\d_]{1,2}|\d+[\\/]\d+")


class LintError(ValueError):
    """Outgoing text holds banned content; the message gives hit count, kinds and offsets only."""

    def __init__(self, offsets: tuple[int, ...], kinds: tuple[str, ...]) -> None:
        self.offsets = offsets
        self.kinds = kinds
        where = ", ".join(
            f"{kind} at {offset}" for kind, offset in zip(kinds, offsets, strict=True)
        )
        super().__init__(
            f"lint: {len(offsets)} banned hit(s) in the outgoing text ({where}); "
            "the text was refused and the matched words are not repeated here."
        )


@dataclass(frozen=True)
class _Hit:
    start: int
    end: int
    kind: str


def _casefolded(words: Iterable[str]) -> set[str]:
    return {word.casefold() for word in words if word}


def name_tokens(names: Iterable[str], allow: Iterable[str] = ()) -> set[str]:
    """Return the casefolded letter runs longer than 3 letters from `names`, minus `allow`.

    A name splits on anything that is not a letter, so "Ravel-Stone" gives "ravel" and "stone".
    """
    allowed = _casefolded(allow)
    tokens: set[str] = set()
    for name in names:
        for run in _LETTER_RUN.findall(name):
            token = run.casefold()
            if len(token) >= _MIN_TOKEN_LETTERS and token not in allowed:
                tokens.add(token)
    return tokens


def _phrase_pattern(phrase: str) -> re.Pattern[str] | None:
    words = phrase.split()
    if not words:
        return None
    body = r"\s+".join(re.escape(word) for word in words)
    head = r"(?<!\w)" if re.match(r"\w", words[0]) else ""
    tail = r"(?!\w)" if re.search(r"\w$", words[-1]) else ""
    return re.compile(head + body + tail, re.IGNORECASE)


def _token_pattern(tokens: set[str]) -> re.Pattern[str] | None:
    if not tokens:
        return None
    ordered = sorted(tokens, key=lambda token: (-len(token), token))
    alternation = "|".join(re.escape(token) for token in ordered)
    return re.compile(r"(?<!\w)(?:" + alternation + r")(?!\w)", re.IGNORECASE)


def _hits(
    text: str, names: Iterable[str], extra_banned: Iterable[str], allow: Iterable[str]
) -> list[_Hit]:
    names = list(names)
    allowed = _casefolded(allow)
    found: dict[tuple[int, int], str] = {}

    def add(start: int, end: int, kind: str) -> None:
        found.setdefault((start, end), kind)

    for name in names:
        if " ".join(name.split()).casefold() in allowed:
            continue
        pattern = _phrase_pattern(name)
        if pattern is not None:
            for match in pattern.finditer(text):
                add(match.start(), match.end(), "name")
    token_pattern = _token_pattern(name_tokens(names, allowed))
    if token_pattern is not None:
        for match in token_pattern.finditer(text):
            add(match.start(), match.end(), "name")
    for phrase in extra_banned:
        pattern = _phrase_pattern(phrase)
        if pattern is not None:
            for match in pattern.finditer(text):
                add(match.start(), match.end(), "banned")
    for match in _URL.finditer(text):
        add(match.start(), match.end(), "url")
    for match in _EMAIL.finditer(text):
        add(match.start(), match.start() + len(match.group().rstrip(".-")), "email")
    for match in _HANDLE.finditer(text):
        add(match.start(), match.end(), "handle")
    for pattern in (_DRIVE, _ROOTED, _JOINED):
        for match in pattern.finditer(text):
            run = match.group().rstrip(".-")
            if pattern is _JOINED and _SHORT_UNIT.fullmatch(run):
                continue
            add(match.start(), match.start() + len(run), "path")
    for match in _EXTENSION.finditer(text):
        add(match.start(), match.end(), "extension")
    return [_Hit(start, end, kind) for (start, end), kind in sorted(found.items())]


def lint(
    text: str,
    names: Iterable[str],
    extra_banned: Iterable[str] = (),
    allow: Iterable[str] = (),
) -> list[str]:
    """Return the matched text of every hit in `text`, ordered by start then end offset."""
    return [text[hit.start : hit.end] for hit in _hits(text, names, extra_banned, allow)]


def assert_clean(
    text: str,
    names: Iterable[str],
    extra_banned: Iterable[str] = (),
    allow: Iterable[str] = (),
) -> None:
    """Raise `LintError` if `text` has any hit; the error never repeats the matched text."""
    hits = _hits(text, names, extra_banned, allow)
    if hits:
        raise LintError(tuple(hit.start for hit in hits), tuple(hit.kind for hit in hits))
