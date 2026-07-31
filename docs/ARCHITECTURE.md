# Architecture

## Boundary

The system accepts audio ingredients and produces audio candidates. It has no visual entities or visual dependencies.

## Components

1. **Asset library** — immutable WAV beds, gestures, and future music stems.
2. **XML configuration** — settings, profiles, recipes, and asset metadata.
3. **Generator** — deterministic selection and mixing from a recipe plus seed.
4. **Batch runner** — creates a requested number of candidates.
5. **Technical validator** — checks format, duration, clipping, and loop readiness.
6. **Workbook** — records batches, candidates, provenance, ratings, and decisions.
7. **Approved library** — human-selected outputs only.

## Reproducibility

A candidate is reproducible from:

- generator version;
- recipe ID;
- profile ID;
- random seed;
- exact asset IDs;
- component timing and gain.

The XML file is versioned with the software. Source WAV files are not modified.

## Version 0.1 behavior

The reference generator:

- reads PCM WAV files;
- selects one bed and one gesture;
- loops or trims the bed to the requested duration;
- places the gesture away from the first and last second;
- applies recipe/profile gains;
- mixes with clipping protection;
- writes 48 kHz, 16-bit stereo WAV output.

Music stems, loudness normalization, equal-power fades, and advanced DSP are explicit later steps.

