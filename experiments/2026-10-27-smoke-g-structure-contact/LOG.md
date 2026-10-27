# Smoke test G: structure contact by mask gap and consequence (27 Oct 2026)

Run on all 10 clips on 27 Oct, $0.146 of SAM.
The design it tests is piece 13 of [the forklift scan route](../../docs/forklift-scan-route.md).
Two clips (`bump_guard_cctv_28`, `loading_dock_spotter_08`) had no truck on the first frame, so the box prompt went on frame 12 (1 s) for them, after a retry Brock approved.

## Result

The mask gap alone does not separate contact from a truck that sits in front of a structure in the image.
`collision_racking_22` asserts contact with a consequence.
`bump_upright_cctv_25` reads a gap of 0 px on all 60 frames, from frame 0, because the truck's mast overlaps the upright in the image long before any touch.
Three compliant clips (`loading_dock_spotter_08`, `two_forklifts_vests_09`, `vest_group_cross_10`) read "touched, no visible consequence" from the same effect.
Clip 08 is the load and forks entering the trailer, which is the compliant action.

| Clip | Label (fixed before the run) | Verdict | Gap 0-1 px frames | Max change in zone |
|---|---|---|---|---|
| `collision_racking_22` | assert | contact (zone-surround change) | 23 of 60 | 0.189 |
| `bump_upright_cctv_25` | assert | touched, no visible consequence | 60 of 60 | 0.007 |
| `scrape_rack_cctv_26` | hard | none (closest 2 px) | 0 | 0.001 |
| `near_miss_person_stops_24` | none | touched, no visible consequence (column guard) | 39 of 60 | 0.000 |
| `bump_guard_cctv_28` | assert? | touched, no visible consequence (prompt on frame 12) | 24 of 60 | 0.030 |
| `spotter_ahead_01`, `reversing_spotter_05` | none | none | 0 | 0.000 |
| `loading_dock_spotter_08` | none | touched, no visible consequence (trailer, prompt on frame 12) | 37 of 60 | 0.017 |
| `two_forklifts_vests_09` | none | touched, no visible consequence (far truck, right rack) | 60 of 60 | 0.003 |
| `vest_group_cross_10` | none | touched, no visible consequence (top rack zone) | 21 of 60 | 0.156 |

## Pass marks

The mark reads "`bump_upright_cctv_25` and `collision_racking_22` assert, no compliant clip asserts".
It does not say whether "touched, no visible consequence" counts as an assertion, so both readings are shown.

| Reading of "assert" | 22 | 25 | Compliant clips (5) | Smoke |
|---|---|---|---|---|
| contact or touched | yes | yes | 3 of 5 assert (08, 09, 10) | fails |
| contact (consequence required) | yes | no | 0 of 5 assert | fails |

Neither reading passes.
The second reading fails because the upright shifts too little (0.007) for the fixed change threshold, so 25 stays at "touched".

## What the overlays show

- The SAM masks are right: the truck is cut out cleanly in every frame checked (`scripts/overlay_masks.py`).
- The gap is measured in the image plane, so a mast or a far truck in front of a rack face reads 0 px.
  Clip 09 is the far truck overlapping the edge of the right rack zone.
  Clip 10 is a mast tip overlapping a top rack zone.
  Clip 25 is the mast over the upright from frame 0.
- The 0.156 change on clip 10 is probably the walking group entering the zone surround, which the truck exclusion does not remove (the overlay shows them beside the top rack zone, and the frames were not isolated).

## What this means for piece 13

- A drawn zone in image coordinates needs the floor plane: contact must be a footpoint or fork-tip measurement on the floor, not mask overlap in the image.
  Pieces 5 and 6 of the scan route already project footpoints to floor metres, so the zone should be drawn as a floor strip at the structure's base.
- "Touched, no visible consequence" is a ruling under a contact rule in the design, and this run shows it is the false-alarm path on compliant clips.
  It needs an approach speed or a fork-tip test before it can be raised.
- The change measure needs people excluded (clip 10) and a tuned level for a thin upright (clip 25).
  Neither was tuned here, on purpose: ten clips are too few to tune on and still call the result a test.

## Method

- Camera: the 10 fixed-camera clips from [the forklift scan route](../../docs/forklift-scan-route.md) (5 collision, 5 compliant), 5 s each, 1280 x 720, encoded at 12 fps (60 frames).
  The synthetic clips stay out of git.
- Zones: drawn once per clip by eye (`zones.json`, sha256 starts `8944b1c2c4235bfd`), checked on overlays, and frozen before the first paid call.
- Truck: one SAM image call ("forklift", first frame), the highest-confidence box, then one SAM video call with that box as the prompt on frame 0 (`include_confidence=true`, `propagation_direction=forward`, `store=false`).
- Rule (`scripts/rule.py`): gap of 1 px or less (chessboard distance) for 3 frames in a row, then a consequence from run start to 0.5 s after the run: zone-surround change (3% of pixels changed by more than 30 grey levels, 2 frames in a row) or an abrupt truck stop.
  Every threshold was set before the first call.
  `rule.py` has an offline self-test with four known cases, and it passes.
- Replay: `scripts/score.py` reads the raw track replies and costs $0.
  It needs `meta_sam_parser`, which is not a project dependency.
- The scripts, the zones file, the raw replies and the call records are kept with this experiment's private record.

## Cost

- 12 SAM image calls at $0.0025 (10 on frame 0, 2 retries on frame 12) and 10 SAM video calls (8 at $0.012 for 60 frames, 2 at $0.01 for the 50-frame minimum), so $0.146 by the call records in `calls.jsonl`.
- The approved total was $0.145 for all ten clips.
  The first estimate was about $0.05: that holds only for the five collision clips at about 10 fps with no image calls, and it left out the five negatives.
- The proxy ledger moved by more than this because other runs spent through the same proxy at the same time, so the ledger delta is not this test's cost.

## Open

- Clip 09 tracks only the far truck, because the near truck enters after frame 0.
