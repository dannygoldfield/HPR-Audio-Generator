# HPR Audio Generator

An audio-first, human-in-the-loop system for building a reusable library of short, publication-quality soundtracks.

This repository intentionally knows nothing about portraits, video, episodes, publishing, or analytics. Its only job is to generate, review, and improve audio.

## Creative model

Each candidate is generated from:

1. one continuous **bed**;
2. zero, one, or two nearby **gestures**;
3. an optional **music stem**;
4. a recipe, profile, and deterministic random seed.

The generator creates constrained surprises. A human listens, rates, and decides what enters the approved library.

## What is included

- 73 source WAV files: 21 beds and 52 gestures
- `config/generator.xml`: the machine-readable source of truth
- `config/generator.xsd`: validation schema for the XML
- `data/HPR-Audio-Generator.xlsx`: the human-facing production workbook
- a dependency-free Python reference generator
- tests, documentation, and empty output folders

## First run

Requires Python 3.11 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
hpr-audio validate
hpr-audio generate --recipe AR-001 --count 10
hpr-audio review-batch --recipe AR-008 --batch-id AB-20260824-004 \
  --count 10 --seed 2026073001 --target-lufs -22
```

Generated candidates are written to `audio/output/candidates/`. Their IDs, seeds, and ingredients should then be recorded in the workbook.

## Source of truth

- Software reads `config/generator.xml`.
- Humans review and curate in the canonical [HPR Audio Generator Google Sheet](https://docs.google.com/spreadsheets/d/1FMn9FkLIMa5SL9_ZnA9NKVo0qUYFxqDQG_-ubW_69CA/edit).
- WAV files remain immutable ingredients.
- Generated audio is reproducible from recipe ID, generator version, and seed.

The Google Sheet is the live operational workbook. Do not commit exported workbook copies to this repository.

## Confirmed pilot reference

`AB-20260731-003` is the human-confirmed ten-track reference batch. Recipe
`AR-007` plus seeds `2026073001` through `2026073010` must reproduce those
files exactly; automated reference checks protect that behavior.

The approved seven-second tracks are their own duration bank. Seven-, nine-,
and eleven-second loops are independent composition families: never stretch,
repeat, or repair a shorter track to populate a longer bank.

`tools/bank_reference_batch.py` fingerprints and registers the exact approved
seven-second reference files. `tools/fresh_eleven_batch.py` composes native
eleven-second candidates with a structurally periodic ambient layer and finite
events that stay clear of the loop boundary. It applies only constant gain to
the approved -22 LUFS review level, rejects combinations that cannot reach that
level below the true-peak ceiling, and never compresses or limits. Human
continuous-playback review remains the authority on whether a loop is
invisible. The nine-second family will be designed separately after the
eleven-second method is approved.

## Initial goal

Generate and review audio independently until the system can reliably produce 150 approved loops. Generated candidates do not count toward the goal; only tracks explicitly marked `Approved` count.
