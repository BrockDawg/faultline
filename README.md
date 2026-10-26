# faultline

Give it a list of rules.
It watches the video, decides whether each rule was followed, and names who broke it.

faultline is a rules-compliance judge that works across domains.
The rules arrive as a rules pack: a folder of markdown rule files plus a `pack.json`.
Any domain whose rules can be written down and seen on video can bring its own pack.
It covers rules compliance only; it gives no clinical advice.

## Forklifts

faultline reviews warehouse forklift incidents.
It reads rules packs based on OSHA 29 CFR 1910.178, the US federal rules for powered industrial trucks.
Each forklift rule says what a breach looks like on video and cites the clause it comes from.
Given incident footage, it says for each rule whether it was followed and which operator or truck broke it.

## PitBot

faultline enforces sim-racing league rules for PitBot (pitbot.gg), a league management platform.
This is league rules enforcement and incident adjudication (esports governance).
It reads rules packs for oval, road and open-wheel leagues, with league values filled in by each league.
Given a steward-report clip, it says for each rule whether it was followed and which car broke it.

## How to run

```sh
uv sync --group dev
uv run pytest
uv run ruff check .
```

After cloning, run `uv run python scripts/install_hooks.py` once.
It installs the commit hook that stamps each commit with its provenance trailers.
Hand-written commits say so in the message with `Built-With: <name> (by hand)`.

## Provenance

[PROVENANCE.md](PROVENANCE.md) says what was built during the hackathon, what existed before it, and which models were used.
[BUILD_LOG.md](BUILD_LOG.md) is the dated log of every commit, generated from git.
