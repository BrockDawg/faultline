# Experiments

Each experiment here has one log: the question, how it ran, what it cost, what was found and what was decided.
Every paid call ran through the metering proxy, under a spend cap, except two sub-cent test calls noted in the Spark Open log.
The tooling named in the logs is private and is described in [PROVENANCE.md](../PROVENANCE.md).

| Date | Experiment | Question | Headline figure |
|---|---|---|---|
| 2026-10-26 | [Capability probe](2026-10-26-capability-probe/LOG.md) | What can Meta's models do on each candidate steward feature? | All 29 probes that can run have run: 15 worked, 14 worked badly; top score 0.75, a local uncertainty signal for the router |
| 2026-10-26 | [Steward limits](2026-10-26-steward-limits/LOG.md) | Given a driver's incident report and the evidence clip, can a video-only steward work out who is who, find the incident, rule correctly and show evidence a human steward can check? | First batch: 18 right, 4 wrong, 3 not scorable for $1.998; second batch: 18 right, 5 wrong, 10 not scorable for $5.14 |
| 2026-10-26 | [Router tier 2: Spark Open](2026-10-26-router-spark-open/LOG.md) | Can Muse Spark Open replace `muse-spark-1.3` as the router's tier 2 without losing answer quality? | Spark Open passed 49 of 55 (89.1%) against Spark 1.3's 50 of 55 (90.9%), at about the same cost per call |
| 2026-10-26 | [Discovery 3](2026-10-26-discovery-3/LOG.md) | Which of 28 follow-up tests on footage, telemetry and tools change the steward design? | 26 of 28 tests ran for $5.59; the pipeline finds the moment but fails on who is who |
| 2026-10-27 | [Router tier 1: Glimmer on Modal](2026-10-27-router-glimmer-modal/LOG.md) | Can Muse Glimmer on a Modal L40S answer tier 1 at a usable speed, and which of the 220 labelled prompts can it answer? | Glimmer answered all 220 prompts from Modal in 14 minutes; a strict re-judge and fresh reviewers moved 35 labels up and 9 down; the routed bench scored 92.7% (51 of 55), level with all-tier-3; Modal cost $2.68, all covered by credits |
