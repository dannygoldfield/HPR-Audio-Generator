# Data Model

## Entities

### SoundAsset

An immutable source WAV with a permanent `SA-` identifier, role, family, format metadata, rights note, status, and creative notes.

### AudioProfile

Creative and technical constraints shared across recipes: density, energy, gains, timing exclusions, and gesture count.

### AudioRecipe

A reusable generation instruction referencing one profile and optional asset-family filters.

### GenerationBatch

One execution of one recipe with a generator version, requested count, seed strategy, timestamps, and status.

### AudioTrack

One generated candidate with a permanent `AT-` identifier, recipe, batch, seed, file path, technical result, human rating, and decision.

An approved track may be assigned to at most one published video. Once assigned, its lifecycle status becomes `Retired` and it is excluded from all future assignment pools. This preserves a one-video/one-soundtrack identity.

### AudioComponent

The provenance link between an AudioTrack and a SoundAsset, including role, order, timing, gain, fades, and processing.

## Relationships

```text
AudioProfile 1 ── * AudioRecipe
AudioRecipe  1 ── * GenerationBatch
GenerationBatch 1 ── * AudioTrack
AudioTrack   1 ── * AudioComponent
SoundAsset  1 ── * AudioComponent
```

The schema deliberately contains no portrait, animation, candidate-video, selection, episode, publishing, or audience-analytics entity.
