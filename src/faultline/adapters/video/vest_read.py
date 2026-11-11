"""The vest read: Wonder looks at a person the colour read could not read.

The script's vest read (measure.read_vest) needs a torso band at least MIN_HEIGHT_PX tall and a box
clear of the frame edge; a small walker far up the aisle, or one cut by the edge, reads "unknown" on
most frames and hi-vis is "unable to rule" naming person.vested. This module crops that person on
the frames where they are largest, sends the crops to Wonder three times, and keeps the answer only
when all three reads agree.

What ships, and why only one way: three agreeing "yes" reads complete the fact as "vested" (with the
read cited in the evidence). An agreeing "no" is recorded and cited but does not make the person
unvested, so this read can clear a person and never puts a breach on anyone; a breach still needs
the script's own colour read. The read was calibrated before use on the people the script itself
reads (the calibration script and its pass mark are in the private build notes).

What every prompt carries: the crops (no frame of the wider scene), the words "warehouse CCTV" and
the question.
No rule text, no measured value, no label and no clip name. Replies live in the record
(record/clips/<sha>/vest/), keyed on the clip's sha, the person's track id and the frames (never the
window seconds), so replay never calls and a judge run over the same frames reads the recorded
reply; Wonder is asked only where none is.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from faultline.adapters.video import client, video
from faultline.adapters.video.video import FPS, H, W

MODEL = "muse-wonder-1.0"
RUNS = 3
TEMPERATURE = 0.7
N_FRAMES = 3  # the person's largest boxes, at least a second apart where the track allows
CROP_GROW = 2.2  # the crop around the person's box
MIN_CROP = 120  # px, full frame
OUT_H = 384  # each crop scaled to this height
MAX_TOKENS = 6000  # Wonder reasons before it answers
READ_ON = True  # a constant, never an environment variable; rides in record.rule_constants()

PROMPT = (
    "These {n} images are crops of the same person, from one warehouse CCTV camera, a "
    "second or more apart. "
    "Question: is this person wearing a high-visibility vest or jacket (fluorescent yellow, "
    "lime or orange, "
    "usually with reflective bands) on the torso?\n"
    "Judge only the clothing on the person's torso. Ignore the floor, racking, the forklift "
    "and any other person.\n"
    'Reply with JSON only: {{"hi_vis": "yes" | "no" | "unclear", "why": "<one short '
    'sentence>"}}. Read {run} of {runs}.'
)


def constants() -> dict:
    return {
        "VEST_READ": READ_ON,
        "VEST_MODEL": MODEL,
        "VEST_RUNS": RUNS,
        "VEST_TEMPERATURE": TEMPERATURE,
        "VEST_N_FRAMES": N_FRAMES,
        "VEST_CROP_GROW": CROP_GROW,
        "VEST_MIN_CROP": MIN_CROP,
        "VEST_OUT_H": OUT_H,
        "VEST_PROMPT_SHA": hashlib.sha256(PROMPT.encode("utf-8")).hexdigest(),
    }


def pick_frames(boxes: dict[int, list[int]]) -> list[int]:
    """The largest boxes first, each at least a second from the ones already picked; then fill by
    size.
    """
    by_area = sorted(
        boxes, key=lambda f: (-(boxes[f][2] - boxes[f][0]) * (boxes[f][3] - boxes[f][1]), f)
    )
    out: list[int] = []
    for f in by_area:
        if all(abs(f - g) >= FPS for g in out):
            out.append(f)
        if len(out) == N_FRAMES:
            break
    for f in by_area:
        if len(out) == N_FRAMES:
            break
        if f not in out:
            out.append(f)
    return sorted(out)


def crop_of(box: list[int]) -> list[int]:
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    h = max((y1 - y0) * CROP_GROW, MIN_CROP)
    w = max((x1 - x0) * CROP_GROW, h * 0.75)
    w, h = min(w, W), min(h, H)
    left = int(round(min(max(cx - w / 2, 0), W - w)))
    t = int(round(min(max(cy - h / 2, 0), H - h)))
    return [left, t, int(round(w)), int(round(h))]


def _scale_h(img: np.ndarray, out_h: int) -> np.ndarray:
    h, w = img.shape[:2]
    out_w = max(2, int(round(w * out_h / h)) // 2 * 2)
    yi = np.clip((np.arange(out_h) * h / out_h).astype(int), 0, h - 1)
    xi = np.clip((np.arange(out_w) * w / out_w).astype(int), 0, w - 1)
    return np.ascontiguousarray(img[yi][:, xi])


def parse(text: str) -> str:
    low = (text or "").lower()
    m = re.search(r'"hi_vis"\s*:\s*"(yes|no|unclear)"', low)
    return m.group(1) if m else "unparsed"


def agreed(answers: list[str]) -> str | None:
    if len(answers) == RUNS and len(set(answers)) == 1 and answers[0] in ("yes", "no"):
        return answers[0]
    return None


def key_of(csha: str, oid: str, pick: list[int], crops: list[list[int]]) -> tuple[dict, str]:
    """The read's key: the clip's sha, the person's track id, the frame indexes and crops sent, and
    the read's constants.

    Never the window seconds: a scorer's windows over the same frames must find the recorded reply,
    not pay for a fresh one."""
    key_obj = {"clip": csha, "person": oid, "frames": list(pick), "crops": crops, **constants()}
    return key_obj, hashlib.sha256(json.dumps(key_obj, sort_keys=True).encode("utf-8")).hexdigest()


def read(perc, oid: str, frames: list[int], allow_calls: bool) -> dict | None:
    """The three reads for this person on these frames: the recorded reply where one exists (any
    window over the same frames), a Wonder call only where none does and calls are allowed, else
    None.

    It is not gated by --words: it is a measurement that feeds the hi-vis verdict, so it belongs in
    the canonical run."""
    if not READ_ON:
        return None
    pm = perc.person_masks().get(oid) or {}
    boxes = {f: list(map(int, pm[f]["box"])) for f in frames if f in pm}
    if len(boxes) < N_FRAMES:
        return None
    pick = pick_frames(boxes)
    crops = [crop_of(boxes[f]) for f in pick]
    key_obj, key = key_of(perc.csha, oid, pick, crops)
    p: Path = perc.dir / "vest" / f"{key}.json"
    if p.exists():
        perc.used.add(p)
        return json.loads(p.read_text(encoding="utf-8"))
    if not allow_calls or not perc.allow_decode:
        return None
    rgb = perc.rgb()
    imgs = []
    for f, (left, t, w, h) in zip(pick, crops, strict=False):
        imgs.append(
            video.jpeg_of(
                _scale_h(np.ascontiguousarray(rgb[f][t : t + h, left : left + w]), OUT_H), quality=3
            )
        )
    replies, answers, spent = [], [], 0.0
    for run in range(1, RUNS + 1):
        msg = PROMPT.format(n=len(imgs), run=run, runs=RUNS)
        r = client.chat(
            [{"role": "user", "content": msg}],
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            images=imgs,
            tag=f"vest:{perc.csha[:8]}:{oid}:{run}",
        )
        replies.append(r["text"])
        answers.append(parse(r["text"]))
        spent += r["est_usd"]
    src = [f * (video.SRC_FPS // FPS) for f in pick]
    rec = {
        "key": key_obj,
        "src_frames": src,
        "replies": replies,
        "answers": answers,
        "agreed": agreed(answers),
        "est_usd": round(spent, 6),
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec, indent=1, sort_keys=True, ensure_ascii=True) + "\n")
    perc.used.add(p)
    return rec
