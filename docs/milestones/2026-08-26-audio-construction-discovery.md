# Audio construction discovery — 2026-08-26

This milestone marks the moment the audio system became understandable as a
set of ingredients rather than an opaque generator. While reviewing the large
11-second batch and moving among portraits, Danny could hear how beds,
gestures, and music stems combined—and could already recognize possible
portrait matches. That listening experience is the reason for adding the
Ingredient Audit.

## What is frozen

- Audio Generator code immediately before the audit: `a79241cd9088b9bfbe8ea5a093a4aa1069e55dc3`
- HPR Umbrella code and review behavior at capture: `e0ad658a72e309b41fe959b71a97c9df0bc2dfc8`
- Locked generator configuration: `config/generator-0.3.1-reference.xml`
- Locked configuration SHA-256: `d5b2a3baed38e5681a5f6363be894b7e7a4874127a85bb980c295656fcf7be5b`
- Source library: 90 immutable WAV ingredients (21 beds,
  52 gestures, 17 music stems)
- Approved bank at capture: 23 tracks (10 at seven seconds,
  13 at eleven seconds)

## Screened 11-second construction that was working

- Native 11-second composition; never stretched or repeated from seven seconds
- Structurally periodic continuous ambience with events kept clear of the boundary
- Bed target: -35.0 dBFS
- Gesture target: -40.0 dBFS
- Music target: -34.0 dBFS
- Delivery target: -22.0 LUFS by constant gain only
- No compression or limiting
- Final loop judgment remains human: close the eyes and hear no transition

## Approved 11-second tracks at capture

- `AUD-11S-E765B98466` — rating 4
- `AUD-11S-E060F315B3` — rating 4
- `AUD-11S-0B9B7E0164` — rating 5
- `AUD-11S-9D45F48CDF` — rating 5
- `AUD-11S-8A301B04D1` — rating 5
- `AUD-11S-E5CF521B62` — rating 5
- `AUD-11S-1DA3726016` — rating 5
- `AUD-11S-DC20A685AB` — rating 4
- `AUD-11S-ED00F6FD49` — rating 5
- `AUD-11S-4CE0E3C117` — rating 4
- `AUD-11S-80917D8B1D` — rating 4 — I am realizing how important the first few seconds are.
- `AUD-11S-82785C5D86` — approved without a numeric rating — This one is for the photo of the boy from Argentina.
- `AUD-11S-51EB5571A8` — rating 5 — Uganda

## What the Ingredient Audit may change

It may record an ingredient as Active, Paused, or Rejected for future candidate
generation, plus a rating and listening note. It may not edit, rename, move, or
delete a WAV file. Prior manifests and approved audio remain intact.

The complete machine-readable snapshot—including the full ingredient roster,
approved-track ingredients, seeds, file hashes, and paths—is in
`data/milestones/2026-08-26-audio-construction-discovery.json`.
