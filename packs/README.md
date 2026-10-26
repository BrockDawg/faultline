# Rules packs

A rules pack is a folder that holds one `pack.json` and one or more markdown rule files.

```
my-pack/
    pack.json
    01-first-rule.md
    02-second-rule.md
```

`pack.json` is a JSON object with a `name`, a `version` and a `domain`, all non-empty strings, plus an optional `source`.
A pack may also set `"unique_ids_across_domain": true`, and then no other flagged pack in the same domain may reuse one of its rule ids.

Rule files are read in file-name order.
Each one opens with a header between two `---` lines that gives the rule's `id` and `title`, followed by the rule text.

```
---
id: some_rule
title: The rule's title
---
The rule text, in plain markdown.
```

`faultline.pack.load_pack(folder)` loads one pack, and `faultline.pack.load_packs(root)` loads every pack folder under a root.

## The packs in this folder

These seven packs existed before the hackathon and come into this repo as data.
Their `pack.json` metadata was edited; no rule text was changed.

### Sim racing

`oval`, `road-gt` and `open-wheel` come from PitBot's Rule Library, for league rules enforcement and incident adjudication (esports governance).
Each holds its discipline's sections plus the universal ones, with `[placeholders]` where a league sets its own values.
Their domain is `sim-racing`.

### Warehouse forklifts

The four `forklift-*` packs cover operating and travel, loads and stacking, pedestrians and site, and truck checks and fuelling.
They are based on OSHA 29 CFR 1910.178 (powered industrial trucks), a US federal regulation in the public domain.
Each rule carries an `On video:` line saying what a breach looks like on incident video, and a `Source:` line naming its clause.
Their domain is `warehouse-forklift`, and rule ids are unique across the four packs.

faultline judges rules compliance only; it gives no clinical advice.
