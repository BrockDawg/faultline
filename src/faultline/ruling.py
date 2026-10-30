"""The model's read: prompt assembly, strict reply checks, three runs and the agreement gate.

This module holds no domain words: the caller (an adapter) supplies the subject noun, the
verdict classes (`Verdicts`) and the prompt's role and document words (`Wording`).

Contract:

- `Verdicts(classes, naming)`: `classes` is the caller's verdict labels with the meaning the
  prompt gives each, in prompt order; `naming` is the one label whose reply names a subject.
  Every other label names none.
- `build_prompt(rule_text, facts, candidates, report_text, frame_labels, subject_noun,
  verdicts, wording)` returns the prompt text: the pack's own rule text as the rules, the fact
  sheet, the closed candidate list, the filed document with names replaced, the frames as
  `frame 1..n` with their stream second, and the question (which candidate, if any, the rules
  hold responsible, and the verdict class). `frame_labels` is a list of (label, stream second)
  pairs; `label_frames` builds it. The prompt never says that an absence of touching means no
  action is due: that line was the biggest confound measured in the earlier rounds, so the
  code never writes it.
- `schema(candidates, verdicts, enum=True)` is the strict reply schema for `response_format`:
  `offender` as `anyOf[{enum: candidates}, {type: null}]`, or with `enum=False` the pattern
  form that worked with images (`^[0-9]{1,3}$` or null); `verdict` from the caller's labels;
  `reason` a string (no length keywords: batch 2's A5 never sent them, so `validate` checks
  the 40 to 600 characters after the call); `frames_used` a list of frame labels.
  `client.chat` wraps it as `{"type": "json_schema", "json_schema": {"name": ..., "strict":
  true, "schema": ...}}`.
- `validate(reply_text, candidates, frame_labels, verdicts)` parses one reply (the whole
  text, else the last fenced block) and returns the checked dict, or None for a failed run:
  not JSON, a key given twice, not an object, a missing or extra key, an offender outside the
  closed set, a verdict outside the labels, a reason outside 40 to 600 characters, an empty
  `frames_used` or a frame label not in the list, the naming verdict with no offender, or an
  offender named with any other verdict.
- `read(prompt, images, model, ledger, ref, ..., verdicts)` runs the lint over every outgoing
  text first (a hit raises `LintError` before any call), then asks `runs` times. Run k adds a
  last text part `Request reference: <ref>-run<k>`, so the metering proxy's cache never
  serves one reply as three, and that line is part of the ledger key (`Ledger.key` over the
  full text with the reference, the image sha256 list, and `client.request_params(model,
  schema, max_tokens)`). A ledger hit sends nothing; a miss calls `client.chat(...,
  spent_entries=ledger.entries())` and always stores the reply first, whatever follows: its
  usage as reported (an absent count stays null and is priced by the per-call fallback), the
  proxy's `cached` word and raw `X-Tourney-Cache` header, and `name_hit` (whether the reply's
  reason failed the name check, never the matched text). Only then can it refuse: a real reply
  (ledger key `source` "model") whose stored `cached` is not False raises `RulingError`
  naming its reference, on the run that sent it and on any later run that reads it back.
  The name check is the lint's person kinds only (`assert_clean(..., paths=False)`: names,
  `extra_banned`, emails, @handles, URLs), never its path shapes, since the model is shown no
  path. Every run is judged again from the stored reply text: a validated reply whose reason
  fails the name check (stored `name_hit` true, or the check run again with the names given)
  is a failed run; the run carries on. An entry written before this rule holds `lint_hit`
  (the full prompt lint) instead; it is read past and never decides, so such a reply is
  judged by the name check alone. A replay that passes no names sees a stored `name_hit`,
  but for an old entry it can only check emails, handles and URLs, so a name hit in an old
  entry makes its replay differ from the line and refuse (it fails closed).
  With `replay_only=True` a ledger miss raises `RulingError` instead of calling the client,
  so a replay can never spend; `source` (replay only) is the ledger key's recorded source.
  `agreed` is true only when every run validates and all give the same offender and verdict;
  then the read carries that offender, verdict and the first run's reason. Otherwise
  offender, verdict and reason are null. The read's `source` is the ledger key's source, so
  a fake read never passes as a real one.
  `json_mode=True` sends the strict schema; `json_mode=False` sends no `response_format` and
  checks the reply after the call, the same way.

Every refusal raises `RulingError`, whose message names the reason and never a key or token.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from faultline import client
from faultline.ledger import Ledger, sha256_text
from faultline.lint import LintError, assert_clean

__all__ = [
    "DEFAULT_RUNS",
    "OFFENDER_PATTERN",
    "REASON_MAX",
    "REASON_MIN",
    "REPLY_KEYS",
    "ModelRead",
    "RulingError",
    "Verdicts",
    "Wording",
    "build_prompt",
    "label_frames",
    "read",
    "run_reference",
    "schema",
    "validate",
]

REPLY_KEYS = ("offender", "verdict", "reason", "frames_used")
REASON_MIN = 40
REASON_MAX = 600
OFFENDER_PATTERN = "^[0-9]{1,3}$"
DEFAULT_RUNS = 3
DEFAULT_MAX_TOKENS = 12000
_FENCE = re.compile(r"```(?:json|JSON)?[ \t]*\n(.*?)```", re.DOTALL)


class RulingError(ValueError):
    """The ruling step refused its input or a reply; the message says why."""


@dataclass(frozen=True)
class Verdicts:
    """The caller's verdict classes: (label, meaning) pairs in prompt order, and `naming`."""

    classes: tuple[tuple[str, str], ...]
    naming: str

    def __post_init__(self) -> None:
        labels = [label for label, _meaning in self.classes]
        if not labels or any(not label.strip() for label in labels):
            raise RulingError("verdicts need at least one non-empty label")
        if len(set(labels)) != len(labels):
            raise RulingError("verdict labels must be distinct")
        if self.naming not in labels:
            raise RulingError(f"the naming verdict {self.naming!r} is not one of the labels")

    @property
    def labels(self) -> tuple[str, ...]:
        return tuple(label for label, _meaning in self.classes)


@dataclass(frozen=True)
class Wording:
    """The prompt's caller words: `role` (with its article) and `document` (the filed text)."""

    role: str
    document: str


# ------------------------------------------------------------------------------- the prompt


def label_frames(stream_seconds: Sequence[float]) -> list[tuple[str, float]]:
    """(label, stream second) pairs: `frame 1` for the first image sent, and so on."""
    return [(f"frame {i}", round(float(s), 1)) for i, s in enumerate(stream_seconds, start=1)]


def build_prompt(
    rule_text: str,
    facts: Sequence[str],
    candidates: Sequence[str],
    report_text: str,
    frame_labels: Sequence[tuple[str, float]],
    subject_noun: str,
    verdicts: Verdicts,
    wording: Wording,
) -> str:
    """The prompt text for one ruling; see the module docstring for its sections."""
    noun = subject_noun.strip()
    if not noun:
        raise RulingError("build_prompt needs a subject noun (the adapter's name for a subject)")
    role, document = wording.role.strip(), wording.document.strip()
    if not role or not document:
        raise RulingError("build_prompt needs the caller's role and document words")
    if not rule_text.strip():
        raise RulingError("build_prompt needs the pack's rule text")
    if not candidates:
        raise RulingError("build_prompt needs a closed candidate list; it is empty")
    fact_lines = [f"- {f.strip()}" for f in facts if f.strip()] or ["- (no facts measured)"]
    frame_lines = [f"{label}: stream second {second:.1f}" for label, second in frame_labels]
    if not frame_lines:
        frame_lines = ["(no frames)"]
    listed = ", ".join(candidates)
    meanings = "\n".join(f"- {label}: {meaning.strip()}" for label, meaning in verdicts.classes)
    sections = [
        f"You are {role} applying written rules to one {document}. Rule from the rules below, "
        "the measured facts and what the frames show.",
        "RULES\n" + rule_text.strip(),
        "FACTS (measured by code, not by a person)\n" + "\n".join(fact_lines),
        f"CANDIDATES\nThe only {noun} numbers that may be named: {listed}. "
        "Name one of these, or none.",
        f"{document.upper()} (as filed, with names replaced)\n" + report_text.strip(),
        "FRAMES (the images follow in this order)\n" + "\n".join(frame_lines),
        "QUESTION\n"
        f"Which candidate {noun}, if any, do the rules above hold responsible for what the "
        f"{document} describes, and which verdict class applies?\n" + meanings,
        "ANSWER\nReply with one JSON object and nothing else, with exactly these keys: "
        '"offender" (one candidate number as a string, or null), "verdict" (one of '
        + ", ".join(f'"{v}"' for v in verdicts.labels)
        + f'), "reason" ({REASON_MIN} to {REASON_MAX} characters, citing the rule and what '
        'the frames show), "frames_used" (the labels of the frames you relied on, such as '
        '"frame 2").',
    ]
    return "\n\n".join(sections) + "\n"


# ------------------------------------------------------------------------------- the schema


def schema(candidates: Sequence[str], verdicts: Verdicts, enum: bool = True) -> dict[str, Any]:
    """The strict reply schema; `enum=False` gives the pattern form for the offender."""
    if enum:
        if not candidates:
            raise RulingError("schema needs at least one candidate for the offender enum")
        offender: dict[str, Any] = {
            "anyOf": [{"type": "string", "enum": list(candidates)}, {"type": "null"}]
        }
    else:
        offender = {"anyOf": [{"type": "string", "pattern": OFFENDER_PATTERN}, {"type": "null"}]}
    return {
        "type": "object",
        "properties": {
            "offender": offender,
            "verdict": {"type": "string", "enum": list(verdicts.labels)},
            "reason": {"type": "string"},
            "frames_used": {"type": "array", "items": {"type": "string"}},
        },
        "required": list(REPLY_KEYS),
        "additionalProperties": False,
    }


# ------------------------------------------------------------------------------- the checks


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _v in pairs]
    if len(set(keys)) != len(keys):
        raise ValueError("a key is given twice")
    return dict(pairs)


def _loads(text: str) -> Any:
    return json.loads(text, object_pairs_hook=_no_duplicates)


def _parse(text: str) -> Any:
    body = text.strip()
    try:
        return _loads(body)
    except ValueError:
        pass
    blocks = _FENCE.findall(body)
    if not blocks:
        return None
    try:
        return _loads(blocks[-1].strip())
    except ValueError:
        return None


def validate(
    reply_text: str, candidates: Sequence[str], frame_labels: Sequence[str], verdicts: Verdicts
) -> dict[str, Any] | None:
    """The checked reply, or None when the run failed (see the module docstring)."""
    data = _parse(reply_text)
    if not isinstance(data, dict) or set(data) != set(REPLY_KEYS):
        return None
    offender = data["offender"]
    if offender is not None and (not isinstance(offender, str) or offender not in candidates):
        return None
    verdict = data["verdict"]
    if not isinstance(verdict, str) or verdict not in verdicts.labels:
        return None
    if (verdict == verdicts.naming) != (offender is not None):
        return None
    reason = data["reason"]
    if not isinstance(reason, str) or not REASON_MIN <= len(reason) <= REASON_MAX:
        return None
    used = data["frames_used"]
    labels = set(frame_labels)
    if not isinstance(used, list) or not used:
        return None
    if not all(isinstance(u, str) and u in labels for u in used):
        return None
    return {"offender": offender, "verdict": verdict, "reason": reason, "frames_used": used}


# ------------------------------------------------------------------------------- the read


@dataclass(frozen=True)
class ModelRead:
    """The model's read over `runs` runs, plus what the record needs to replay it."""

    model: str
    runs: int
    agreed: bool
    verdict: str | None
    offender: str | None
    reason: str | None
    parse_failures: int
    source: str = "model"
    lint_hits: int = 0
    refs: tuple[str, ...] = ()
    keys: tuple[str, ...] = ()
    sent_refs: tuple[str, ...] = ()
    replies: tuple[dict[str, Any] | None, ...] = field(default=())

    def as_dict(self) -> dict[str, Any]:
        """The ruling line's `model_read` object, plus `parse_failures`, `lint_hits` and
        `source` ("fake" or "model")."""
        return {
            "model": self.model,
            "runs": self.runs,
            "agreed": self.agreed,
            "verdict": self.verdict,
            "offender": self.offender,
            "reason": self.reason,
            "parse_failures": self.parse_failures,
            "lint_hits": self.lint_hits,
            "source": self.source,
        }


def run_reference(ref: str, k: int) -> str:
    """The last text part of run k: `Request reference: <ref>-run<k>`."""
    return f"Request reference: {ref}-run{k}"


def _image_bytes(images: Sequence[bytes | Path | str]) -> list[bytes]:
    return [im if isinstance(im, bytes) else Path(im).read_bytes() for im in images]


def _usage(reply: client.Reply) -> dict[str, int | None]:
    """Both counts as reported; an absent count stays None and is priced by the fallback."""
    return {name: reply.usage.get(name) for name in ("prompt_tokens", "completion_tokens")}


def _name_hit(text: str, names: list[str], extra_banned: list[str], allow: list[str]) -> bool:
    """Whether a reply's reason names a person: the lint's person kinds only, no path shapes.

    The model is shown no path, so a path shape in its reason ("9.5/9.5.2", "-0.7m/s") cannot
    leak one; a name it read from a missed card, an address or a link can.
    """
    try:
        assert_clean(text, names, extra_banned, allow, paths=False)
    except LintError:
        return True
    return False


def read(
    prompt: str,
    images: Sequence[bytes | Path | str],
    model: str,
    ledger: Ledger,
    ref: str,
    *,
    candidates: Sequence[str],
    frame_labels: Sequence[str],
    verdicts: Verdicts,
    names: Iterable[str],
    extra_banned: Iterable[str] = (),
    allow: Iterable[str] = (),
    runs: int = DEFAULT_RUNS,
    schema: Mapping[str, Any] | None = None,
    json_mode: bool = True,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    replay_only: bool = False,
    source: str | None = None,
) -> ModelRead:
    """Ask `runs` times through the ledger and gate on agreement; see the module docstring.

    `schema` defaults to the module's `schema(candidates, verdicts)`; it is sent only when
    `json_mode` is true. `replay_only` refuses any ledger miss instead of calling the client.
    `source` (replay only) is the recorded `source` of the ledger key's params ("fake" or
    "model"), so a replay finds the keys its run wrote whatever the current fake-model setting
    is.
    """
    if runs < 1:
        raise RulingError(f"runs must be at least 1, not {runs}")
    if not ref.strip() or any(ch.isspace() for ch in ref):
        raise RulingError("the request reference must be non-empty with no spaces")
    names = list(names)
    extra_banned = list(extra_banned)
    allow = list(allow)
    texts = [(prompt, run_reference(ref, k)) for k in range(1, runs + 1)]
    for body, tail in texts:
        assert_clean(body + "\n\n" + tail, names, extra_banned, allow)
    sent_schema = (schema or _schema(candidates, verdicts)) if json_mode else None
    params = client.request_params(model, sent_schema, max_tokens)
    if source is not None:
        if not replay_only:
            raise RulingError("a recorded source is for a replay only (replay_only=True)")
        params["source"] = source
    blobs = _image_bytes(images)
    shas = [hashlib.sha256(b).hexdigest() for b in blobs]

    keys: list[str] = []
    sent: list[str] = []
    checked: list[dict[str, Any] | None] = []
    lint_hits = 0
    for k, (body, tail) in enumerate(texts, start=1):
        run_ref = f"{ref}-run{k}"
        full = body + "\n\n" + tail
        key = Ledger.key(model, params, full, shas)
        keys.append(key)
        entry = ledger.get(key)
        if entry is None and replay_only:
            raise RulingError(
                f"{run_ref}: the ledger has no reply for key {key}; a replay never calls the model"
            )
        if entry is None:
            messages = [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": body}, {"type": "text", "text": tail}],
                }
            ]
            reply = client.chat(
                messages,
                model,
                blobs,
                sent_schema,
                max_tokens,
                spent_entries=list(ledger.entries()),
            )
            first_check = validate(reply.text, candidates, frame_labels, verdicts)
            hit = first_check is not None and _name_hit(
                first_check["reason"], names, extra_banned, allow
            )
            # The call is paid: the reply is stored before any refusal below.
            entry = ledger.put(
                key,
                {
                    "model": model,
                    "params": params,
                    "prompt_sha": sha256_text(full),
                    "image_shas": shas,
                    "reply": reply.text,
                    "usage": _usage(reply),
                    "finish_reason": reply.finish_reason,
                    "cached": reply.cached,
                    "cache_header": reply.cache_header,
                    "name_hit": hit,
                },
            )
            sent.append(run_ref)
        if params.get("source") != "fake" and entry.get("cached") is not False:
            raise RulingError(
                f"{run_ref}: the metering proxy did not say this reply was fresh (cached "
                f"{entry.get('cached')!r}), so it cannot count as a run; the reply is kept in "
                "the ledger, which counts its spend"
            )
        # Judged again from the stored reply text every time. An old entry's `lint_hit` (the
        # full prompt lint, path shapes included) is read past and never decides.
        run = validate(str(entry["reply"]), candidates, frame_labels, verdicts)
        if run is not None and (
            entry.get("name_hit") is True or _name_hit(run["reason"], names, extra_banned, allow)
        ):
            lint_hits += 1
            run = None
        checked.append(run)

    failures = sum(1 for c in checked if c is None)
    good = [c for c in checked if c is not None]
    agreed = (
        failures == 0
        and len({(c["offender"], c["verdict"]) for c in good}) == 1
        and len(good) == runs
    )
    first = good[0] if agreed else None
    return ModelRead(
        model=model,
        runs=runs,
        agreed=agreed,
        verdict=first["verdict"] if first else None,
        offender=first["offender"] if first else None,
        reason=first["reason"] if first else None,
        parse_failures=failures,
        source=str(params.get("source")),
        lint_hits=lint_hits,
        refs=tuple(f"{ref}-run{k}" for k in range(1, runs + 1)),
        keys=tuple(keys),
        sent_refs=tuple(sent),
        replies=tuple(checked),
    )


_schema = schema
