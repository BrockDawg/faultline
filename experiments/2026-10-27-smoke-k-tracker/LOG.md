# Smoke test K: the tracker with operator exclusion (27 Oct 2026)

Scripts only, no paid call, $0.
The design it tests is piece 4 of [the forklift scan route](../../docs/forklift-scan-route.md); the hi-vis rerun is piece 7's "70% of frames" rule.

## Question

Can a deterministic tracker over recorded DETR boxes keep one id per person across a clip and drop the truck's operator, without ever dropping a pedestrian?

## Verdict

**The mark is not met: two of the five hand-labelled drivers were dropped, not five.**
The other three marks hold: no pedestrian was dropped (13 of 13 kept), ids did not swap on either named clip, and two full runs were byte-identical.
The three missing drivers are a detector limit, not a tracker fault, and none of them became a pedestrian.

## Method

- Detections: [smoke test H](../2026-10-27-smoke-h-detector-ruling/LOG.md)'s pinned DETR ResNet-50 (revision `1d5f47bd`, weights SHA-256 `830f5e2e…`), CPU, one thread per worker, deterministic algorithms, score 0.9, boxes rounded to whole pixels.
  It ran on every frame of the 16 fixed-camera clips: 1,936 frames, 1,919 person boxes, about 17 minutes a run on 12 workers.
  The clips and the weights stay out of git.
- Tracker: Hungarian assignment over a cost of 0.5 × (1 − IoU) + 0.5 × footpoint distance (capped at one box height).
  A pair may match if IoU is at least 0.05 or the footpoints are within 0.5 box heights (widened 10% per missed frame).
  A track is born after 3 matched frames, a tentative track dies on its first miss, a confirmed track ends after 24 unmatched frames (1 s at 24 fps), and there is no appearance re-identification.
  Ids are given in order of birth.
- Operator rule: a track is the operator if its box centre sits inside a truck box on more than 50% of its matched frames.
  Truck boxes are smoke H's hand-drawn stand-ins, drawn once on frame 60 and applied to every frame.
- Score: each person in [smoke test E](../2026-10-27-smoke-e-hi-vis/LOG.md)'s hand key is matched to the track whose box on the labelled frame has IoU of at least 0.3 with the hand box.
  A driver passes if that track is dropped, a pedestrian if it is kept; a person with no matching track counts against the mark.
- Hi-vis over tracks: E's own person read, thresholds and median-background mask, unchanged, run on every matched frame of every track.
  A track is ruled unvested only if at least 70% of its matched frames read unvested.
- All thresholds were written down before the first run and not changed after it.
- Two full runs (detection, tracker, score, hi-vis) were compared byte for byte.

## Result

| Pass mark (fixed first) | Result |
|---|---|
| Five hand-labelled drivers dropped | **Fail: 2 of 5** (`loading_dock_spotter_08` d1, `reversing_no_spotter_14` d1) |
| No pedestrian dropped | **Pass: 0 of 13 dropped**, all 13 matched to a kept track |
| Ids do not swap on `vest_group_cross_10` and `no_vest_group_near_11` | **Pass** for the labelled people (detail below) |
| Two runs byte-identical | **Pass**: detections, tracks, score and hi-vis output all match (`23189e6b…`, `26c42596…`, `815eddf7…`, `e3b45fdc…`) |

### The three drivers that were not dropped

- `near_miss_person_stops_24` d1: DETR saw the driver and the tracker dropped the track (88% of frames inside the truck box), but on the labelled frame the detector's box and the hand box overlap at IoU 0.183, under the 0.3 line fixed first.
  Read by eye on the contact sheet this one is a drop, which would make it 3 of 5; the recorded score stays 2 of 5 because the line was fixed first.
- `scrape_rack_cctv_26` d1 and `two_forklifts_vests_09` d1: DETR boxed no person at all on the labelled frame.
  The cab frame hides them, so there is nothing to drop, and no pedestrian was made of them either.
  E's hand boxes read these two drivers as unvested (0.000 and 0.039); with the detector they never reach the colour rule.

### Operators found that the key did not label

The operator rule dropped 7 tracks in all and 0 pedestrians; 5 of the 7 did not match a driver in E's key.

| Clip | Track | Frames | In truck | What it is |
|---|---|---|---|---|
| `no_vest_pedestrian_03` | 1 | 66 | 89% | a small person in the cab, seen on the contact sheet; the key and the hand count both say no driver |
| `no_vest_group_near_11` | 1 | 111 | 80% | the seated driver; the hand count lists one, E's key leaves them out |
| `near_miss_person_stops_24` | 2 | 78 | 88% | the driver, see above |
| `two_forklifts_vests_09` | 2 | 8 | 100% | the second truck's driver, frames 108 to 120 only |
| `reversing_no_spotter_14` | 2 | 8 | 100% | a short second track on the driver, frames 91 to 99 |

The nearest a pedestrian came to the line was the reversing spotter in `reversing_spotter_05`, at 25% of frames inside the truck box.

### Ids on the two named clips

- `no_vest_group_near_11`: two kept tracks, both 121 frames, and neither the left-right nor the near-far order of the pair flipped once.
- `vest_group_cross_10`: the three labelled people kept tracks 1, 2 and 4 for 81, 102 and 107 frames, with smooth motion and no near-far order flip between any pair of them.
  The left-right order of tracks 1 and 2 flipped twice over 65 common frames, because the two stand almost one above the other; their footpoints never swapped.
- The group is four people, not three (the hand count says 4, E's key lists 3).
  The fourth was split into three short tracks of 19, 24 and 7 frames, so six kept tracks for four people.
  Those are fragments, not a swap, but the fourth person's id is not stable, and every other order flip on the clip involves those fragments.
- The by-eye check used contact sheets with the track ids drawn on; they hold frames of the synthetic clips and stay out of git.

## Hi-vis rule over the tracks, against E's one frame

Pedestrian tracks only, because drivers are dropped first.

| Measure | E, one frame | K, every frame of the track (70% rule) |
|---|---|---|
| Vested people ruled unvested | 0 of 9 | **0 of 9** |
| Unvested people found | 4 of 4 | **4 of 4** (shares 1.00, 0.76, 0.85, 1.00) |
| Vested people reading vested | 6 of 9 (3 unknown) | 8 of 9 with a vested share of at least 0.5 |
| Drivers that would be ruled unvested if counted | 2 (one frame each) | 2 (`loading_dock_spotter_08` at 75%, the unlabelled `no_vest_group_near_11` driver at 87%) |

- Two of the three people E left at unknown now read vested on most frames: `reversing_spotter_05` p1 on 60% (E: cut by the frame edge) and `vest_group_cross_10` p2 on 72% (E: 0.134).
- The third, `spotter_ahead_01` p1, is the case the 70% rule exists for.
  The person stands still, the median background absorbs them, and across 121 frames they read unvested on 47% of frames and vested on 38%.
  A single-frame unvested read would have been a false breach on many of those frames; the 70% line ruled it "not unvested", with the share 23 points under the line.
- Exclusion before the colour test is needed: two drivers read unvested on more than 70% of their frames, because the cab frame hides the vest.

## What it does not prove

- Truck boxes are hand-drawn once and held still, so the operator rule never met a truck box that follows a moving truck.
  A pedestrian walking through a stand-in box for more than half their frames would be dropped; none did, but that is untested rather than designed out.
- Drop is decided per track over the whole clip.
  The design's "stays an operator for 2 s after leaving the truck" and the link to a parked truck are not built or tested; no driver in these clips climbs down.
- 13 pedestrians and 5 labelled drivers on AI-made clips, one detector, one camera angle per clip.
  There is no occlusion by racking and no crossing of two people in the key, so the real-footage cases named in piece 4 are still open.
- The drivers DETR does not see (2 of 5, plus one with a poor box) need the truck mask from SAM or a seated-person test; the tracker cannot drop what the detector did not box.
- Id stability is checked by motion order and by eye, not against per-frame hand labels.
- The key's driver labels are incomplete (the hand count lists seven seated drivers, the key lists five), so "drivers" in the pass mark depends on which list is read.

## What this says for the design

- Piece 4 works as designed for pedestrians: none dropped, ids stable for the labelled people, byte-identical.
- The operator rule is only as good as the person detector's recall in the cab, so the "dropped" mark belongs with piece 3's truck masks, not with the tracker alone.
- A group in close overlap fragments a person into short tracks; it does not swap them.
  Anything that counts people (a pedestrian count, a dwell time) should merge or ignore tracks under about 1 s.

## Files

The detection, tracker, score, hi-vis, viewer and order-flip scripts, every box, the tracks, the score and the hi-vis output of run 1 are kept with this experiment's private record; run 2 matched them byte for byte.
The clips, the pinned weights and the contact sheets stay out of git.
