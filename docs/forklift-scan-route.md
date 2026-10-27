# Forklift scan route: deterministic pieces for long footage with no report

This note designs the forklift route of the steward in scan mode.
The input is long footage from one fixed warehouse camera, with no incident report.
The output is a list of rulings for a review dashboard, each with its rule, its offender and its evidence window.
Scripts find the candidate moments and measure what happened; a model is used only where pixels need perception (people and trucks) or judgement (the ruling text).
It reuses five ideas from the steward's racing route: an entry roster of who took part, a closed set of the few candidates near an incident, a shot-cut gate, a leak lint on everything that leaves the machine, and a read ledger that records every model read once.
Three racing designs are its starting points and are extended here: a floor homography with zone polygons, a hi-vis colour rule, and a painted-number read snapped to a roster.
It is a design note, not a build plan.

## Why this route exists

The customer is the insurer and the site's management.
The steward scans long footage, finds what nobody reported, and a site that shows good practice earns a lower insurance rate.
Every scan produces a list of identified incidents, and each one is a ruling: rule, offender, evidence window.
A dashboard shows the list; the insurer confirms or denies each incident; management can dispute any of them; the insurer has the final say.
Each human decision is a label that feeds an agreement measurement.
Output is always rulings, never tips or statistics, though a tally of rulings is fine.
Hi-vis vest and spotter checks are a required capability even though they are site rules, not OSHA clauses.
A truck is identified by the fleet number painted on it, matched to the site's fleet roster (one entry id per truck), never by faces.
People are never identified: a person is only "a person" with a position.

## Decisions Brock made

- One fixed camera is enough on its own; two-camera fusion waits for real footage.
- Hi-vis vest and spotter checks are a required capability: they are site rules, not OSHA clauses, but they are common on real sites.
- The site rules get their own pack: `forklift-site-rules` in this repo holds `hi_vis_in_truck_zone`, `spotter_when_reversing`, `pedestrian_separation` and `structure_contact`, each citing the site as its source.

## Ground rules for this round

- **One fixed camera is enough on its own:** every piece, test and smoke measure in this note uses a single camera.
- **Two-camera and multi-view fusion are out of scope for this round:** the synthetic clips that carry a front and a back view (`pairs/`, `superseded/pairs_v1/` and the two-view sources) are mostly wrong and do not work, so fusing views needs real, non-synthetic footage before it can be investigated.
- **Driver-view (POV) footage is out of scope for scan mode:** a camera on the truck moves with it, so no floor calibration holds; the static-camera gate (piece 1) refuses it.
- **Reproducible by construction:** scripts are deterministic; every model read is recorded once in the read ledger, keyed by the SHA-256 of model id, version, parameters and input bytes, and replayed from there on every rerun.
- **Paid calls only on Brock's go**, through the metering proxy.

## What is on disk to test against

The synthetic clips are AI-made (Kling 3.0 Turbo, one Seedance clip), 5 s each, 1280 × 720 at 24 fps, and each carries an AI-generated audio track.
The folder name is the label.
Measured on 27 Oct, 16 of them are single, fixed-camera clips, and they are the test set for this route.

| Folder | Fixed-camera clips used here |
|---|---|
| `compliant/` | `spotter_ahead_01`, `reversing_spotter_05`, `loading_dock_spotter_08`, `two_forklifts_vests_09`, `vest_group_cross_10` |
| `non_compliant/` | `no_vest_pedestrian_03`, `no_vest_group_near_11`, `blind_corner_no_vest_07`, `no_spotter_04`, `reversing_no_spotter_14`, `speeding_forklift_06` |
| `collisions/` | `collision_racking_22`, `near_miss_person_stops_24`, `bump_upright_cctv_25`, `scrape_rack_cctv_26`, `bump_guard_cctv_28` |

Left out, with the reason:

- All 8 clips in `forklift_pov/`, plus `collisions/bump_upright_pov_27` and `collisions/collision_pallet_stack_23`: driver views; the frames show that 23 is a driver view too, although it sits in `collisions/`.
- `compliant/spotters_front_and_back_02`: the camera tracks the truck sideways (the racks slide by about a bay between the first and last frame).
- `compliant/spotters_front_and_back_02_alt`: the camera pans 15 px over the clip.
- `pairs/`, `superseded/` and `model_test/`: two-view material, out of scope this round.

Earlier measurements that shape this design:

- Spark Open scored 19 of 20 on the forklift clips with the filename in the prompt and 11 of 20 with an opaque case reference (Discovery 3, W1-15); with the opaque reference it called four compliant spotter clips near misses and missed both no-spotter clips.
  The 19 of 20 results from batch 1 and batch 2 F1 also had the filename in the prompt, so no clean model-only score on these clips exists yet.
- SAM 3.1's "forklift" concept tracked the truck, and the bump on `bump_upright_cctv_25` is a 0 px mask gap for 29 frames (F2); "racking upright" returned the whole rack and "column guard" returned nothing.
- SAM 3.1's "person" concept counts the seated driver (F3: 4 vested where the label says 3).
- A single findings slot squeezed a missing vest into a near miss (batch 1 run 24); findings must be a list, one per rule.
- A touch with no visible consequence is invisible to frame-sampled Spark (batch 1 run 25); a bump needs mask-level evidence between frames.

## 1. Rule by rule: what pixels can judge

There are 46 forklift rules in the four packs, plus two site rules that do not exist in any pack yet.
"Scan" means a script can raise a candidate on its own; "window" means the rule is judged only inside a window that another rule's signal raised; "out" means no camera can judge it in scan mode, and the table names the evidence source that can.
Measurable from pixels deterministically: **yes** (a script can measure it on a calibrated fixed camera), **partly** (a script raises the candidate and judgement settles it), **no**.
The model column names the perception model needed; the ruling call itself is always a model and is not repeated there.

### forklift-operating-travel (14)

| Rule id | Measurable | Signals | Model for perception | Route |
|---|---|---|---|---|
| `travel_speed` | partly | truck track, floor homography, speed-limit zone, deceleration, obstacle distance ahead | truck detector | scan |
| `following_distance` | yes | two truck tracks, same heading, gap in truck lengths (length from the roster) | truck detector | scan |
| `no_passing_at_blind_spots` | partly | two truck tracks swapping order inside an intersection or blind-corner zone | truck detector | scan |
| `slow_and_horn_at_cross_aisles` | partly | speed inside the cross-aisle zone against the approach speed; horn only if the camera records sound | truck detector | scan (speed), window (horn) |
| `watch_travel_path` | no | operator head direction while moving; small, occluded, and close to reading a person | none in scan | window |
| `load_blocks_view` | partly | load top above the overhead guard (image ratio) while travelling forks first | truck and load masks | scan |
| `smooth_turns` | partly | heading rate times speed (a lateral-acceleration proxy), load-shed blobs | truck detector | scan |
| `ramps_and_grades` | partly | ramp zone with its grade and uphill direction from the site file; forks-first direction; forks height | truck and forks masks | scan, only where a ramp is drawn |
| `wet_floor_speed` | partly | speed inside a wet-area zone the site marks; a wet floor itself is not reliably visible | truck detector | scan, only where marked |
| `avoid_loose_objects` | partly | new stationary blob in a travel lane (background model), truck footprint crossing it | truck detector | scan |
| `no_horseplay` | partly | spin (high heading rate at low ground speed), two trucks side by side above the limit | truck detector | scan, judgement-heavy |
| `limbs_inside_truck` | no | limbs outside the truck outline; too small at CCTV distance | none in scan | window |
| `parked_truck` | partly | truck stationary, the operator leaving the truck and walking over 7.6 m (25 ft) away or out of view, forks raised, truck moving with nobody in it; power state is not visible | truck, person and forks masks | scan |
| `yield_to_emergency_vehicles` | no | emergency vehicle with lights; very rare indoors | none | out (site incident log) |

### forklift-loads-stacking (7)

| Rule id | Measurable | Signals | Model for perception | Route |
|---|---|---|---|---|
| `stable_load` | partly | load mask shifting against the forks, falling blobs (fast downward motion) | load mask | scan |
| `rated_capacity` | partly | truck mask pitching forward (principal-axis rotation); the weight itself is not visible | truck mask | scan for tip-overs; out for weight (telematics load sensor) |
| `long_or_high_loads` | partly | load box size against the truck, load mask meeting a racking zone, sway | load mask | scan |
| `forks_fully_under` | no | fork-tip engagement; too fine at CCTV distance | none in scan | window |
| `no_forward_tilt_when_raised` | no | mast tilt with forks high away from a rack; mast angle is a fine read | none in scan | window |
| `load_backrest` | partly | objects falling toward the operator side of the truck | load mask | scan |
| `overhead_clearance` | partly | mast or load mask meeting a drawn overhead-fixture zone (pipe, sprinkler, door header), plus a consequence | truck and load masks | scan |

### forklift-pedestrians-site (10)

| Rule id | Measurable | Signals | Model for perception | Route |
|---|---|---|---|---|
| `no_driving_at_trapped_person` | yes | person inside a fixed-object margin zone (rack face, wall, bench), truck closing toward them under a distance | person and truck detectors | scan |
| `no_one_under_forks` | partly | person footpoint inside the floor area under raised forks or load | person detector, forks mask | scan |
| `no_riders` | partly | a second person overlapping the truck while it moves, outside the operator seat position | person detector, truck mask | scan |
| `dock_edge_distance` | yes | truck footprint distance to the drawn dock-edge line (the site sets the distance); door pushing is not measurable | truck detector | scan |
| `trailer_secured` | partly | trailer edge moving inside the dock-door zone while a truck is inside; chocks are a judgement read | none for movement | scan for creep; out for chocks (dock-lock and restraint logs) |
| `railcar_secured` | partly | rail car moving inside its zone during loading | none for movement | scan where a rail dock exists |
| `dockboard_secured` | partly | speed over the drawn dockboard zone; plate movement in the zone | truck detector | scan |
| `rail_track_crossing` | yes | crossing angle between truck heading and the drawn track line; parked distance to the track centre under 2.44 m (8 ft) | truck detector | scan |
| `elevator_entry` | partly | speed and angle entering a lift zone; floor level and power are not visible | truck detector | scan |
| `fire_access_clear` | yes | truck or load stationary inside a fire-aisle, stair or extinguisher zone beyond a dwell time; abandoned load as a new stationary blob | truck detector, background model | scan |

### forklift-truck-checks-fuelling (15)

None of these can be judged by a scan of floor CCTV.
They are truck state, maintenance and fuelling procedure, and the evidence is in records.
They stay in the pack so a window raised by another rule can cite one when a clear frame shows it (a visible fuel trail, a missing overhead guard), but scan mode never raises them.

| Rule id | Measurable | Evidence source that can judge it |
|---|---|---|
| `unsafe_truck_out_of_service` | no | maintenance work orders, telematics fault codes and lockouts |
| `pre_shift_check` | no | pre-shift checklists (paper or electronic), telematics check-lockout records |
| `overhead_guard` | no (in scan) | truck inspection records; a window frame may show it |
| `truck_lighting` | partly | a lux survey of the area; a camera's auto exposure hides real light levels, so pixel brightness only flags "dark" |
| `no_unapproved_changes` | no | maintenance records and manufacturer approvals |
| `exhaust_sparks_or_overheating` | no | maintenance records, telematics engine temperature |
| `refuel_engine_off` | no | telematics ignition state joined to the fuel log |
| `fuel_spill_cleared` | no | telematics ignition joined to fuel and housekeeping logs |
| `no_fuel_leak` | no | maintenance records; a window frame may show a trail |
| `no_open_flame_checks` | no | fuelling-area procedures, and a dedicated fuelling-bay camera judged in a window only |
| `battery_change_position` | no | charger and battery-change logs |
| `battery_handling_equipment` | no | equipment register |
| `charging_area_no_flames` | no | a charging-room camera judged in a window, hot-work permits |
| `battery_top_clear` | no | battery-room procedures |
| `electrolyte_mixing` | no | battery-room procedures and equipment register |

### Site rules that need a pack (required capability)

Vests and spotters are not in the four packs, so the scan has nothing to cite yet.
A fifth pack, for example `forklift-site-rules`, would hold them with the site as the source.

| Proposed rule id | Measurable | Signals | Model for perception | Route |
|---|---|---|---|---|
| `hi_vis_in_truck_zone` | yes | person inside a truck-operating zone, torso colour test (piece 7), three states: vested, unvested, unknown | person detector | scan |
| `spotter_when_reversing` | partly | truck reversing (travel against its fork end) where the site requires a spotter (blind zone, dock, or a load that blocks view), a vested person near the rear path | person and truck detectors, forks mask | scan |

Two more site rules are worth Brock's decision, because the collision clips need something to cite: `pedestrian_separation` (a site distance between a moving truck and a person; the experiments' W2 used 3 m) and `structure_contact` (any contact between a truck and racking, uprights, guards or stacked stock; the experiments' W3).
The OSHA packs reach these only indirectly, through `travel_speed` ("cannot stop before ... object") and `long_or_high_loads` ("hits racking").
A trap to handle before adding the pack: `tests/test_packs.py` checks that every rule in the `warehouse-forklift` domain cites a `1910.178(` clause, so a site pack in that domain fails the test until the test allows a site source for packs that declare one.
Both are now done in this repo: the four rules are the `forklift-site-rules` pack, and the test allows a pack whose source is the site.

### Summary of scope

- **Scan (a script raises candidates):** 26 rules, plus the two site rules.
- **Window only (judged when another rule's window shows it):** `watch_travel_path`, `limbs_inside_truck`, `forks_fully_under`, `no_forward_tilt_when_raised`, and the horn half of `slow_and_horn_at_cross_aisles`.
- **Out of scope for video:** `yield_to_emergency_vehicles` and all 15 rules of `forklift-truck-checks-fuelling` in scan mode, plus the weight half of `rated_capacity` and the chocks half of `trailer_secured`; their evidence is checklists, telematics, maintenance and charger records.

## 2. The scan pipeline, as scripts

Each step says whether it is a **script**, a **fixed-weight model** (frozen perception, recorded in the ledger) or the **judgement model**.
One fixed camera feeds the whole pipeline.

1. **Ingest (script).**
   `ffprobe` records the container's duration, frame rate, start time and pts; every later time is a frame index mapped back by code.
   The media is hashed (SHA-256) and given an opaque case id from the first 12 hex characters; metadata and chapters are stripped (`-map_metadata -1 -map_chapters -1`).
   Frames are sampled at fixed rates: 8 fps greyscale at 160 × 90 for the activity gate, 2 fps at full size for the detectors on active seconds only, and 12 fps inside candidate windows.
   An on-screen CCTV timestamp, where the recorder burns one in, is read by digit templates (the method that reads the racing broadcast's clock strip, [smoke test B](../experiments/2026-10-27-smoke-b-clock-strip/LOG.md)) to give wall-clock time and the night flag.
2. **Shot and static-camera gate (script).**
   ffmpeg's `scdet` finds cuts (recorder restarts, a PTZ preset change, a spliced export).
   Within each segment, the border-band test and a phase-correlation shift check refuse a moving camera, and the first frame is compared with the camera's calibration reference frame, so a camera knocked out of position is refused rather than scanned with a stale calibration.
   `freezedetect` marks frozen stretches (a dead feed is not "no incidents") and `blackdetect` marks dark ones.
3. **Calibration per camera (script, set up once by a person).**
   A site file per camera holds four or more floor points with known positions in metres, plus a fifth point held out to check the fit, and the homography solved in numpy by direct linear transform (no OpenCV needed).
   It also holds zone polygons in image coordinates: aisles, pedestrian walkways, cross aisles, blind corners, racking faces, dock edges, dockboards, fire aisles and equipment, rail tracks, lift doors, speed-limit zones with their limits, ramps with grade and uphill direction, overhead fixtures, and truck-operating zones.
   Each zone names the rule ids it serves.
   The file records the reference frame's hash, the camera's height and a colour reference patch for the vest rule.
4. **Activity gate (script).**
   A moving-pixel fraction on the 8 fps greyscale stream, with hysteresis, picks the seconds where anything moves; only those seconds go to the detectors, which is what makes a two-hour clip affordable.
5. **Detection (fixed-weight model, recorded).**
   People: Meta's DETR ResNet-50 (`facebook/detr-resnet-50`, Apache-2.0), run locally on the CPU with a fixed thread count, its Hugging Face revision and weight-file SHA-256 recorded in every ledger row, boxes rounded to whole pixels.
   Trucks: SAM 3.1 (`sam-3.1` on Meta's API) with the "forklift" concept on active seconds, plus box prompts on each truck and its fork end inside candidate windows for masks; COCO detectors have no forklift class.
   Every reply goes into the read ledger by input hash and is replayed from there.
6. **Tracks (script).**
   Detections are joined frame to frame by box overlap and the Hungarian assignment (`scipy.optimize.linear_sum_assignment`), with fixed rules for track birth, death and gaps, and no learned re-identification.
   A person whose box centre sits inside a truck's mask is that truck's operator, never a pedestrian.
   Persons get clip-local ids (`P1`, `P2`); trucks get track ids that piece 15 maps to roster entry ids.
7. **Derived signals per frame (script).**
   Footpoints (the bottom centre of the mask or box) are projected to floor metres; speed and heading come from Savitzky-Golay smoothing over 1 s (`scipy.signal.savgol_filter`).
   Per frame: truck speed against the zone's limit; deceleration; truck-to-person minimum distance and closing speed; truck in each zone; truck-to-truck gap in truck lengths; forks or load raised (piece 14); travel direction against the fork end (reversing, piece 9); vest state of each person in a truck zone (piece 7); spotter present while reversing; dwell time of a stationary truck or load in a fire zone; mask gap to a drawn structure zone (piece 13); a new stationary blob in a lane.
8. **Event candidates (script).**
   Each rule has a spec: signal, comparison, on and off thresholds, minimum duration, merge gap and cooldown.
   A hysteresis state machine turns per-frame signals into episodes, deduplicated by rule, truck and person, so a two-hour clip yields a short list.
9. **Windowing (script).**
   Each candidate becomes a window from 4 s before onset to 3 s after the end, clipped to its segment; a window that a cut or a frozen stretch clips is marked "evidence incomplete".
   Overlapping windows on the same truck merge into one window carrying several rule candidates.
10. **Evidence pack (script).**
    Eight frames per window are chosen by code (onset, peak signal, end, and evenly between), with head regions blurred, labelled by frame index, and zones and measured values drawn on by script; the leak lint checks every outgoing string and file name.
11. **The ruling (judgement model, one call per window).**
    Spark, or Spark Open if a measurement favours it, gets the window's rule texts from the pack, the fact sheet of measured signals, the closed set of truck entry ids, the persons as "a person at x m", and the eight frames.
    It returns a list of findings, one per rule, each with a verdict, an offender from the closed set, the rule id from the pack, evidence frame indices from those it was sent, and the ruling text.
    Tools are closed, output headroom is 16,000 tokens, and the reply is recorded in the ledger.
12. **Post-checks and the list (script).**
    Code rejects any rule id not in the pack, any offender outside the closed set and any frame not sent; where the measured verdict and the model's disagree, both are shown.
    The surviving findings become rows in the rulings table in state `identified`, and the dashboard lists them.

Scripts: steps 1-4, 6-10 and 12.
Fixed-weight models: step 5 only (DETR locally; SAM 3.1 through the API, recorded).
Judgement: step 11 only, once per window.

## 3. The pieces, ranked

The pieces are ranked by what the scan needs first.
Pieces that extend a racing design say so.

| # | Piece | Rules served | Build | Measurable today |
|---|---|---|---|---|
| 1 | Shot and static-camera gate | all | 2-3 h | yes, measured |
| 2 | Activity gate | all (cost and recall) | 1-2 h | yes, measured |
| 3 | Detection ledger | all scan rules | 4-6 h | yes |
| 4 | Deterministic tracker with operator exclusion | all scan rules | 3-4 h | yes |
| 5 | Camera site file, homography and zones | all zone rules | 4-6 h | consistency only |
| 6 | Floor kinematics | speed, gap, turns, dwell | 3-4 h | ordinal only |
| 7 | Hi-vis three-state colour rule | `hi_vis_in_truck_zone`, `spotter_when_reversing` | 3-4 h | yes |
| 8 | Proximity and geometry signals | pedestrian and site rules | 3-4 h | ordinal only |
| 9 | Reversing direction and spotter rule | `spotter_when_reversing`, `load_blocks_view`, `ramps_and_grades` | 4-5 h | yes, 3 clips |
| 10 | Candidate engine with per-rule specs | all scan rules | 4-6 h | yes |
| 11 | Evidence pack, privacy blur and leak lint | all | 3-4 h | yes |
| 12 | Ruling contract and post-checks | all | 3-4 h | yes, with paid calls |
| 13 | Structure contact by mask gap and consequence | `structure_contact`, `overhead_clearance`, `long_or_high_loads`, `travel_speed` | 4-6 h | yes, 5 clips |
| 14 | Forks and load raised | `no_one_under_forks`, `parked_truck`, `load_blocks_view`, `ramps_and_grades` | 3-4 h | weak |
| 15 | Truck identity: roster closed set and stencil read | every ruling's offender | 4-6 h | no footage yet |

Every piece costs $0 to run apart from the SAM 3.1 frames in piece 3 and the ruling calls in piece 12.

### 1. Shot and static-camera gate

- **Rules served:** all; nothing is measured across a cut or on a moving camera.
- **How it works:**
  `scdet` at threshold 10 on a 320 × 180 copy gives the cuts.
  Inside each segment, a border band (the outer ring of the frame, about 10% on each side) is tested for moving pixels between frames two apart; a segment whose border moves on more than 90% of frames is a moving camera.
  Phase correlation between the segment's first and last frame catches a slow pan, and a shift over 5 px refuses the segment.
  The first frame is compared with the calibration reference frame (phase correlation and edge overlap), so a camera knocked off its mount is refused with "recalibrate".
  `freezedetect` and `blackdetect` mark dead and dark stretches, so a dead feed is reported as uncovered time, not as a clean shift.
  This extends the racing route's shot-cut gate from broadcasts to CCTV.
- **Why it is reproducible:** fixed thresholds on pixel statistics, with ffmpeg's version recorded.
- **How to measure it:** measured on 27 Oct on a 421 s shift built from 28 clips (method in section 6).
  `scdet` found 27 of 27 cuts; a home-made frame-difference rule found only 23, missing cuts after high-motion clips, so `scdet` is the tool.
  The border band moved on 97-100% of frames for all 8 `forklift_pov/` clips, for `bump_upright_pov_27`, for `collision_pallet_stack_23` and for `spotters_front_and_back_02`, and the frames confirm that the last three move.
  `spotters_front_and_back_02_alt` showed a 15 px start-to-end shift (a slow pan), and `bump_guard_cctv_28` reached 61%, from the truck entering the frame edge on a fixed camera.
  These thresholds were set after looking at the data, so they need a held-out check: pass is every moving clip refused and every fixed clip kept on clips not used to set them.
  Real footage needed later: a PTZ camera moving between presets, a camera shaken by a passing truck, and a camera nudged out of position.
- **Cost:** $0; 2-3 hours.
- **Smoke (under an hour):** run the gate over the 28 clips one by one and print kept or refused with the reason; the 12 moving clips named above must be refused and the 16 fixed clips kept.

### 2. Activity gate

- **Rules served:** all; it decides which seconds the detectors see.
- **How it works:**
  ffmpeg decodes 8 fps greyscale at 160 × 90; the moving-pixel fraction is the share of pixels whose value changed by more than 15 against the frame two steps back.
  An episode opens above 1.0%, closes after 0.5 s below 0.5%, must last 1 s, and is padded by 2 s.
  Only active seconds go to piece 3, which keeps SAM spend proportional to activity rather than to footage length.
- **Why it is reproducible:** integer arithmetic on decoded frames with one decoder thread; two runs on the same file gave byte-identical output.
- **How to measure it:** measured (section 6): 28 of 28 active spans located, 0 candidates in the idle gaps, an identical output hash on two runs.
  It locates activity, not breaches: every compliant clip also raised a window, as it should.
  Real footage needed later: a full shift from a busy aisle, to measure the active share of the day and the false-activity rate from lighting flicker, shadows and doors.
- **Cost:** $0; 1-2 hours to turn the smoke script into a module.
- **Smoke:** rerun the section 6 test on the 16 fixed-camera clips only, with the same pass marks.

### 3. Detection ledger

- **Rules served:** every scan rule.
- **How it works:**
  People: DETR ResNet-50 run locally on the CPU (a fixed thread count, `torch.use_deterministic_algorithms(True)`), on active seconds at 2 fps and inside windows at 12 fps, "person" class only, boxes rounded to whole pixels.
  Trucks: SAM 3.1's "forklift" concept on active seconds at 2 fps (it tracked trucks in F2), then box prompts on each truck and its fork end inside windows at 12 fps for masks.
  Every reply is written to an append-only ledger keyed by SHA-256 of model id, revision, parameters and input bytes; a rerun reads the ledger and calls nothing unless forced, and a forced call writes a new row and a diff against the old one.
  This extends the racing route's read ledger, which records every model read once by input hash, to the detectors.
- **Why it is reproducible:** DETR's weights are pinned by revision and file hash and run on the CPU; SAM's output is reproducible only through the ledger, because the caller cannot pin the API's weights (see section 5).
- **How to measure it:** on the 16 fixed-camera clips, the person count per frame against a hand count on the middle frame of each clip, with the driver excluded by piece 4 (F3's 4 must become 3), and two runs giving identical ledger keys and boxes.
  Pass: the person count right on at least 14 of 16 middle frames, every truck found in every clip that has one, and zero changed bytes on the rerun.
  Real footage needed later: small, distant people (under 40 px tall) under real CCTV compression, and night footage.
- **Cost:** DETR $0; SAM 3.1 at $0.0002 a frame with a 50-frame minimum per call is about $0.20 for the 16 clips (two prompts at 12 fps), and about $1.44 per prompt per two-hour camera at 2 fps if half the seconds are active; 4-6 hours.
- **Install needed:** torch (CPU build) and transformers, or torchvision for a Faster R-CNN alternative; neither is installed.
- **Smoke:** once installed, run DETR twice on the middle frame of three clips and compare the box lists byte for byte.

### 4. Deterministic tracker with operator exclusion

- **Rules served:** every scan rule; it turns boxes into "this truck" and "a person".
- **How it works:**
  Box-overlap cost, Hungarian assignment, a track born after 3 matched frames and ended after 1 s unmatched, and no appearance re-identification.
  A person whose box centre lies inside a truck's mask (or box, before masks exist) is that truck's operator for as long as they stay there and for 2 s after leaving it, so a driver climbing down is never a pedestrian.
  An operator who walks away keeps a link to the truck, which feeds `parked_truck`.
  Person ids are local to the clip and are never carried across clips, cameras or days.
- **Why it is reproducible:** a fixed cost function and a fixed assignment over recorded boxes.
- **How to measure it:** on the 16 clips, no track switch on clips with one truck, the operator never counted as a pedestrian, and `two_forklifts_vests_09` keeping two truck tracks.
  Real footage needed later: occlusion by racking, and two people crossing.
- **Cost:** $0; 3-4 hours.
- **Smoke:** run it on hand-drawn boxes for `two_forklifts_vests_09` at 2 fps and print the track table.

### 5. Camera site file, homography and zones

- **Rules served:** every rule with a zone, a speed or a distance.
- **How it works:** this extends the racing route's floor design (a site file per camera with floor points for a homography and zone polygons tied to rule ids) with four additions.
  The homography is solved in numpy (direct linear transform on four or more points), so OpenCV is not required.
  A fifth floor point is held out and its reprojection error printed, and the file is refused if the error exceeds 2% of the camera's floor depth.
  Zones carry rule bindings and parameters (a speed limit, a dwell time, a dock-edge distance, a ramp grade), so changing a site's rules is a data change, not a code change.
  A small click tool writes the file from one reference frame, so a site can set up a camera in minutes.
- **Why it is reproducible:** a fixed file, whose hash goes into every ruling.
- **How to measure it:** the synthetic clips have no true scale, so only consistency can be checked: with an assumed aisle width, the held-out point lands within a few pixels on the fixed-camera clips with visible floor lines.
  Real footage needed later: one real camera with five measured floor points.
- **Cost:** $0; 4-6 hours.
- **Smoke:** click four floor corners on `vest_group_cross_10`, solve, and reproject a fifth.

### 6. Floor kinematics

- **Rules served:** `travel_speed`, `following_distance`, `smooth_turns`, `slow_and_horn_at_cross_aisles`, `dockboard_secured`, `elevator_entry`, `fire_access_clear`, `parked_truck`, `rail_track_crossing`.
- **How it works:** footpoints are projected through the homography; Savitzky-Golay smoothing over 1 s gives speed and heading; deceleration comes from the speed series; a truck is stationary under 0.1 m/s for 2 s; truck length for following gaps comes from the roster entry.
- **Why it is reproducible:** arithmetic on recorded tracks.
- **How to measure it:** ordinal only on synthetic clips: `speeding_forklift_06` must have the highest peak floor speed of the trucks in the 16 clips, and the truck in `vest_group_cross_10` must come near zero speed while the group crosses.
  Real footage needed later: a truck with telematics speed, for a metric pass of within 10%.
- **Cost:** $0; 3-4 hours.
- **Smoke:** print the speed series for `speeding_forklift_06` and `vest_group_cross_10` from hand-drawn boxes.

### 7. Hi-vis three-state colour rule

- **Rules served:** `hi_vis_in_truck_zone`, and the "vested" test inside `spotter_when_reversing`.
- **How it works:** this extends the first hi-vis design (a torso-band colour test on person boxes, with the seated driver dropped) with four changes.
  The torso band (20-60% of the person's height) is tested in HSV, computed in numpy, for fluorescent yellow-green and orange-red, after a per-camera white balance from the colour reference patch in the site file.
  The test uses the person's mask where one exists, not the box, so yellow trucks, yellow racking beams and yellow floor lines behind a person do not count as a vest.
  The output has three states: vested, unvested, unknown; a person under 40 px tall, cut by the frame edge, mostly occluded, or in a low-light or infrared segment is unknown, never unvested.
  A person is ruled unvested only if at least 70% of their frames in the zone read unvested.
- **Why it is reproducible:** fixed colour thresholds on recorded boxes and masks.
- **How to measure it:** on the 16 clips, every person in `no_vest_pedestrian_03` and `no_vest_group_near_11` reads unvested, no vested person on the five compliant clips reads unvested, the driver is never counted, and `blind_corner_no_vest_07` (person tiny) may come out unknown.
  Pass: zero vested people read unvested, since a wrong breach is worse than a missed one, and at least 3 of the 4 unvested people found.
  Real footage needed later: grey-cast and sodium lighting, dirty vests, and infrared night mode, where colour is gone and only the retroreflective strips can be tested.
- **Cost:** $0; 3-4 hours.
- **Smoke:** hand-box the people on the middle frame of three compliant and three no-vest clips and print the state per person.

### 8. Proximity and geometry signals

- **Rules served:** `no_driving_at_trapped_person`, `no_one_under_forks`, `no_riders`, `dock_edge_distance`, `rail_track_crossing`, `fire_access_clear`, and the proposed `pedestrian_separation`.
- **How it works:**
  In floor metres: the minimum distance from each person's footpoint to the truck's projected footprint (the mask's floor contact edge, not its box), the closing speed, and the time to contact.
  A person counts as "against a fixed object" when inside the margin zone along a racking face or wall while the truck closes on them.
  The area under raised forks is the floor region ahead of the truck's fork end, used only when piece 14 says the forks are up.
  Distances to drawn lines (dock edge, rail centre) are point-to-segment arithmetic.
- **Why it is reproducible:** geometry on recorded tracks and a fixed site file.
- **How to measure it:** ordinal on synthetic clips: `near_miss_person_stops_24` must have a smaller minimum truck-to-person distance than any compliant clip.
  Real footage needed later: staged walks at measured distances, for a metric pass mark.
- **Cost:** $0; 3-4 hours.
- **Smoke:** print the minimum truck-to-person footpoint distance in image pixels for `near_miss_person_stops_24` and the five compliant clips.

### 9. Reversing direction and spotter rule

- **Rules served:** `spotter_when_reversing`, `load_blocks_view`, `ramps_and_grades`.
- **How it works:**
  The truck's fork end comes from a SAM box prompt on the forks (or the mast) inside the window, taken as a majority over frames; reversing is travel against the vector from the truck's centre to its fork end, held for at least 1 s.
  A spotter is a vested person (piece 7) inside a cone behind the truck's rear, within a site-set distance, on at least half of the reversing frames; again there are three states, with unknown when the rear is out of view.
  Where the site file says a spotter is required (a blind zone, a dock, or a load that blocks the view), reversing with no spotter raises a candidate.
- **Why it is reproducible:** a fixed geometry rule over recorded masks and tracks.
- **How to measure it:** `reversing_spotter_05` must read reversing with a spotter, `reversing_no_spotter_14` reversing with none, and `loading_dock_spotter_08` must not raise a candidate.
  The model with an opaque reference missed both no-spotter clips (W1-15), so this is where scripts should beat the model.
  Real footage needed later: a dock with a site spotter rule.
- **Cost:** $0 plus a few cents of SAM box prompts; 4-5 hours.
- **Smoke:** on hand-drawn truck and fork boxes for `reversing_no_spotter_14`, print the travel direction per second.

### 10. Candidate engine with per-rule specs

- **Rules served:** every scan rule.
- **How it works:**
  One spec per rule in a data file: the signal, the comparison, on and off thresholds, minimum duration, merge gap, cooldown and window padding, plus the rule id it cites from the pack.
  A hysteresis state machine per (rule, truck, person) turns frame signals into episodes; overlapping episodes on the same truck merge into one window with several candidate rules.
  Every candidate carries the signal values that raised it, which become the ruling's fact sheet.
- **Why it is reproducible:** a fixed spec file, whose hash goes into every ruling, over recorded signals.
- **How to measure it:** on the 16 clips, each non-compliant and collision clip must raise a candidate for its labelled rule, and the five compliant clips must raise no vest or spotter candidate.
  Pass: 11 of 11 labelled clips raise their rule, and at most one compliant clip raises any candidate.
  Real footage needed later: a full shift, for the candidates-per-hour rate that sets the insurer's review load.
- **Cost:** $0; 4-6 hours.
- **Smoke:** feed hand-made signal series (a dip under 1.5 m for 0.5 s, then one for 2 s) and check that only the second becomes a candidate.

### 11. Evidence pack, privacy blur and leak lint

- **Rules served:** all; it keeps every call honest and every person anonymous.
- **How it works:** this extends the racing route's case packager, which sends only code-picked frames under an opaque case id and lints every outgoing string.
  Each window becomes `<case id>/<frame index>.jpg`, with frames picked by code, zones and measured values drawn on by script, and the head region of every person box (the top 25%) blurred with a fixed kernel before anything leaves the machine.
  The leak lint refuses any outgoing string or file name that holds a source filename, a folder label, a label word (compliant, no_vest, no_spotter, collision, near_miss, speeding) or a URL.
  No face crop is ever stored.
- **Why it is reproducible:** a hash, a deny list and a fixed blur.
- **How to measure it:** on the W1-15 request texts on disk, the lint flags 20 of 20 filename prompts and 0 of 20 opaque ones, and every person in every pack frame is blurred.
- **Cost:** $0; 3-4 hours.
- **Smoke:** run the lint's patterns over the saved W1-15 request texts, with and without the filename, and count hits per pass.

### 12. Ruling contract and post-checks

- **Rules served:** all; this is the one judgement step.
- **How it works:**
  One call per window, with a strict output schema where it works: a findings list, each with `rule_id` from the window's candidate rules plus the pack (an enum), `verdict` (breach, no breach, cannot judge), `offender` (a truck entry id from the closed set, "a person" with the clip-local id and floor position, or "unable to identify"), `evidence_frames` from the frames sent, and `text`.
  The prompt carries the fact sheet in fixed wording, with a fixed sentence on what each signal does not prove (for example "distances are measured on the floor plane; a person occluded by racking may be closer than shown").
  After the call, code rejects anything outside the enums, and where the measured candidate and the model's verdict disagree, both are kept and shown.
  Stated confidence is not used for gating, since it carried no signal in the racing runs.
- **Why it is reproducible:** the reply is recorded in the ledger by input hash, so the same window returns the same ruling on a rerun.
- **How to measure it:** a paid check on Brock's go: the 16 clips with opaque ids and the fact sheet, against the W1-15 opaque baseline of 11 of 20.
  Pass: no compliant clip ruled a breach, and at least 9 of 11 labelled clips ruled under the right rule.
- **Cost:** about $0.02-0.05 a window going by the batch 1 forklift calls, so under $1 for the 16 clips; 3-4 hours.
- **Smoke:** validate ten hand-written replies, four of them broken on purpose, against the schema and the post-checks.

### 13. Structure contact by mask gap and consequence

- **Rules served:** the proposed `structure_contact`, `overhead_clearance`, `long_or_high_loads`, `travel_speed`.
- **How it works:** this extends the racing route's contact rule ([smoke test C](../experiments/2026-10-27-smoke-c-contact-rule/LOG.md)) to structures.
  Racking faces, uprights, guards and columns are drawn once per camera as zones, because SAM's nouns for them failed (F2); the truck and load masks come from the ledger.
  Contact is stated when the mask meets the structure zone (a gap of 1 px or less) inside one segment and a consequence follows within 0.5 s: pixels inside the structure zone change (the upright shifts), a falling blob appears, or the truck stops abruptly.
  Contact with no consequence is "touched, no visible consequence", which is still a ruling under a contact rule; an approach that stops short is nothing.
- **Why it is reproducible:** a rule over recorded masks and a fixed zone.
- **How to measure it:** `bump_upright_cctv_25` (0 px for 29 frames in F2) and `collision_racking_22` (boxes fall) must assert contact; `scrape_rack_cctv_26` never got under 2 px in F2, so it is the hard case and may come out "possible"; no compliant clip may assert contact.
- **Cost:** about $0.05 of SAM box prompts for the five collision clips; 4-6 hours.
- **Smoke:** draw the upright on `bump_upright_cctv_25`, box-prompt the truck into the ledger, and print the gap per frame.

### 14. Forks and load raised

- **Rules served:** `no_one_under_forks`, `parked_truck`, `load_blocks_view`, `ramps_and_grades`.
- **How it works:** the lowest point of the forks or load mask above the truck's floor contact line, as a ratio of the truck's mask height, with per-camera thresholds for lowered, travel height and raised; "load blocks view" is the load's top above the overhead guard while travelling forks first.
- **Why it is reproducible:** a ratio on recorded masks.
- **How to measure it:** weak on synthetic clips, since few show raised forks; any clip that does is checked by eye.
  Real footage needed later: a racking put-away, the normal raised-forks case.
- **Cost:** a few cents of SAM; 3-4 hours.
- **Smoke:** on one hand-picked frame with a load, print the ratio.

### 15. Truck identity: roster closed set and stencil read

- **Rules served:** every ruling's offender.
- **How it works:** this extends the first stencil design (painted digits read against the site's templates from two agreeing frames, snapped to the fleet roster).
  The site roster holds, per entry id, the fleet number, model, colour, mast type, length and the cameras where the truck works; the closed set for a window is the roster entries allowed on that camera, narrowed by visible attributes (colour, mast type, length from the floor footprint).
  The stencil read (4× upscale, the site's stencil templates, two agreeing frames, snapped to the closed set) settles the entry; a tie is "unable to identify" with the candidates listed, after one retry from another frame of the same track.
- **Why it is reproducible:** templates and a closed roster.
- **How to measure it:** not possible today, since no clip has a painted fleet number (batch 2 F4 was skipped for this reason).
  For the demo, a synthetic roster with attribute narrowing shows the closed set and the "unable to identify" path honestly.
- **Cost:** $0; 4-6 hours; the stencil half is blocked on footage.
- **Smoke:** render 30 stencil numbers at a range of heights and blurs and find the smallest readable height, to tell a site what camera framing it needs.

## 4. The dashboard and the ruling lifecycle, as data

The thin slice the demo needs by 4 Nov is two tables, one state machine and one list page with buttons per role.

### The rulings table

| Field | Meaning |
|---|---|
| `ruling_id` | hash of scan id, rule id, offender and window |
| `scan_id` | one scan of one camera's footage |
| `site_id`, `camera_id`, `site_file_sha256` | the site file it was measured against |
| `video_sha256` | the footage, by content |
| `pack`, `pack_version`, `rule_id`, `source_clause` | the rule cited, a `1910.178(...)` clause or the site rule |
| `verdict` | breach, no breach, cannot judge, unable to identify |
| `offender_kind` | truck, person or site |
| `offender_entry_id` | the truck's roster entry id, or empty |
| `person_ref` | clip-local "P2", only when the offender is a person; never anything that identifies them |
| `candidates` | roster entry ids when identity is unresolved |
| `window_start_frame`, `window_end_frame`, `window_start_s`, `window_end_s`, `wall_clock_start` | the evidence window |
| `evidence_frames` | the frame indices the ruling cites |
| `mask_ids` | ledger keys of the masks and boxes behind the measures |
| `signals` | the measured values that raised it, each with unit and frame (for example `min_person_distance_m: 1.2 @ 4410`, `vest: unvested 9/10 frames`) |
| `measured_verdict`, `model_verdict` | the script's candidate and the model's finding, both kept |
| `model_id`, `model_ledger_key` | the judgement call, replayable |
| `text` | the ruling text against the pack |
| `evidence_incomplete` | true when a cut or a frozen stretch clips the window |
| `state` | identified, confirmed, denied, disputed, final |
| `final_outcome` | upheld or rejected, once final |

### The decisions table (append-only)

| Field | Meaning |
|---|---|
| `decision_id` | row id |
| `ruling_id` | the ruling decided |
| `from_state`, `to_state` | the transition |
| `actor_role` | system, insurer or site management |
| `actor_account` | the reviewer's account id |
| `reason` | required for a denial and a dispute |
| `at` | time of the decision |

### Who may change state

| From | To | Who |
|---|---|---|
| (new) | identified | system, from a scan |
| identified | confirmed or denied | insurer |
| identified or confirmed | disputed | site management, with a reason |
| disputed | final (upheld or rejected) | insurer |
| confirmed or denied | final | insurer, when the dispute period closes |

Nobody edits a ruling's evidence or text; a correction is a new ruling that supersedes the old one, and both stay.
The system never changes a state after `identified`.

### Agreement measures the insurer sees

Every human decision is a label against the system's ruling.

- **Confirmed rate:** confirmed over (confirmed + denied), from the insurer's first decision.
- **Disputed rate:** disputed over identified.
- **Overturned rate:** final outcomes that differ from the insurer's first decision.
- Each with its count, split per rule id, per truck entry id and per camera.
- **Measured against model:** where the measured verdict and the model's verdict differed, how often the final outcome sided with each.

These are tallies of rulings, not advice.
For the demo, one SQLite file holds both tables, the list page plays each window from its frames, and a role switch stands in for real accounts.

## 5. Risks and traps

### The synthetic clips are AI-made

- They can validate plumbing (gate, ledger, tracker, candidate engine, schema), the colour rule on clean colours, ordinal comparisons (fastest truck, closest person), behaviour on compliant clips (no false breach), and reproducibility.
- They cannot validate metric speeds or distances (there is no true scale, and generated motion need not obey physics), real lighting and compression, a real false-alarm rate per hour, occlusion at real distances, night or infrared footage, horn audio (the audio tracks are generated), or fleet numbers (none is painted).
- Their labels come from frame sheets and some are weak (`blind_corner_no_vest_07`, person tiny; `bump_upright_pov_27`, no clear bump), and 4 of the 20 clips used in earlier runs turned out to have moving cameras.
- Every pass mark here is ordinal or categorical for that reason.

### Filename and label leaks

- Spark Open went from 11 of 20 to 19 of 20 when the filename named the label (W1-15), so the earlier 19 of 20 results do not measure the model.
- The scan sees only an opaque, metadata-stripped file; the label manifest lives in a separate file that no pipeline step reads; the leak lint (piece 11) refuses any call carrying a label word.

### False positives from occlusion

- SAM reads occlusion as touching, and its confidence does not flag it (A7); a person behind racking can sit inside the truck's box in the image while metres away on the floor.
- Proximity is measured on floor footpoints, never on box overlap; a footpoint hidden by racking makes the distance unknown, not small; contact needs a consequence (piece 13).

### Camera motion

- PTZ cameras, vibration from passing trucks and a knocked mount all break a calibration.
- The static-camera gate refuses moving segments and the reference-frame check catches a shifted camera; refused time is reported as uncovered, never as clean.

### Night and low light

- Infrared mode removes colour, so the vest rule must return unknown, not unvested; a retroreflective-strip brightness test is a later piece, for real infrared footage.
- Detector recall drops in low light, so segments under a brightness floor are marked low-light in every ruling that comes from them.

### People on foot who are drivers dismounting

- A driver climbing down would otherwise be a pedestrian beside a truck with no vest.
- The tracker (piece 4) keeps a person leaving a truck's mask as that truck's operator, and the operator's distance from a stopped truck feeds `parked_truck`, not a pedestrian rule.

### Privacy

- Faces and people are never identified: no face detection, no face crops, no re-identification across clips, cameras or days, and person ids are local to one clip.
- Head regions are blurred in every frame that leaves the machine or reaches the dashboard.
- A ruling against a person names "a person" with a position; the accountable party in the dashboard is the site.
- Trucks are identified only by fleet number against the site's roster.

### The detector's reproducibility

- DETR ResNet-50 run locally on the CPU is reproducible from its pinned weights; on a GPU, floating-point order can move a box by a pixel, which is why boxes are rounded and recorded.
- SAM 3.1 through Meta's API cannot be pinned by the caller: the `sam-3.1` id may serve changed weights, results varied between runs in the racing tests, and the concept tracker churns ids in crowds (16 ids, 56 jumps on a pack).
  Its reproducibility comes from the ledger: the first reply is the record, and a rerun replays it.
- Ultralytics YOLO models are a common alternative, but their weights and code are AGPL-3.0, and their COCO weights have no forklift class, so they would need a fine-tune on a forklift dataset with its own licence.

## 6. What to build first

1. **Detection ledger (piece 3), with the tracker (piece 4) as its first consumer.**
   Every other measure reads boxes and masks; recording them once by hash is what makes a two-hour scan reproducible and means SAM is paid for once.
   It is the one step with a model in it before the ruling, so it has to be settled first.
2. **Hi-vis three-state colour rule (piece 7), with the reversing and spotter rule (piece 9) straight after.**
   Vests and spotters are the required capability; they are the cases the model got wrong with an opaque reference (four compliant spotter clips called near misses, both no-spotter clips missed); and 10 of the 16 fixed-camera clips exercise them.
3. **Candidate engine with per-rule specs (piece 10).**
   It is the scan itself: it turns signals into a short list of windows, each tied to a pack rule, and it makes the list of rulings, rather than a model's reading of a clip, the product.

Pieces 1 and 2 are already proven by the smoke test below and only need turning into modules.
The site pack for vests and spotters is decided and built, and the pack test allows a site source.

### The smoke test that proves the scan locator today

Measured on 27 Oct at $0, with ffmpeg 8.1.1, numpy and scipy only.
The smoke scripts live with the experiment record for [smoke test D](../experiments/2026-10-27-smoke-d-forklift-locator/LOG.md).

- **Build:** 28 single-view clips (the 16 fixed-camera clips plus the 12 moving-camera ones, so that the gate is tested too), shuffled with a fixed seed, each preceded by 10 s of its own first frame frozen with temporal noise (`noise=alls=6:allf=t`) to stand in for an idle camera, scaled to 640 × 360, with audio and metadata stripped, joined into one 421.2 s file with an opaque name.
  The label manifest was written to a separate file that the locator never reads.
- **Run:** the activity gate (piece 2) and the cut and camera checks (piece 1), run twice.
- **Result:** both runs wrote byte-identical output; all 28 active spans were located; zero candidates fell in the 28 idle gaps; `scdet` found 27 of 27 cuts where the home-made cut rule found 23; the border-band test separated the 8 driver-view clips and the moving clips named in piece 1.
- **What it does not prove:** precision, since every compliant clip also produced a window; the gate finds activity, not breaches, and breaches come from pieces 7-10.
- **Pass marks for the next run, on the 16 fixed-camera clips only:** every active span located, no idle false alarms, identical output on two runs, and no fixed clip refused by the gate.

## Not verified

- DETR ResNet-50's current Hugging Face revision hash and its recall on real CCTV people, and whether any COCO detector labels a forklift reliably as some class.
- Whether SAM 3 or 3.1 weights can be run locally under Meta's licence, which would make the truck masks pinnable.
- That `torch.use_deterministic_algorithms` with a fixed thread count gives bit-identical DETR boxes across machines.
- Every metric threshold here (speed limits, the 70% vest share, the 1.0% motion threshold on real footage), since the synthetic clips support ordinal checks only.
- The static-camera thresholds, which were set after looking at these clips and need a held-out check.
- Horn detection, fleet-number reading and infrared vest reading, for lack of real footage.
- Two-camera and multi-view fusion, out of scope this round; investigating it needs real, non-synthetic footage.
