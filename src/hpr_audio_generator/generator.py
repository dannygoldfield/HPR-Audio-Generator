from __future__ import annotations

from array import array
from dataclasses import dataclass
from math import pow
from pathlib import Path
import random
import wave

from .config import Asset, Config


@dataclass(frozen=True)
class GeneratedTrack:
    path: Path
    seed: int
    recipe_id: str
    bed_id: str
    gesture_id: str
    gesture_start_sec: float
    music_stem_id: str | None = None
    music_start_sec: float | None = None


def _read_pcm(asset: Asset, config: Config) -> array:
    with wave.open(str(asset.path), "rb") as source:
        actual = (source.getframerate(), source.getnchannels(), source.getsampwidth() * 8)
        expected = (config.sample_rate, config.channels, config.sample_width_bits)
        if actual != expected:
            raise ValueError(f"{asset.asset_id} format {actual} does not match {expected}")
        samples = array("h")
        samples.frombytes(source.readframes(source.getnframes()))
        return samples


def _gain(samples: array, gain_db: float) -> array:
    factor = pow(10.0, gain_db / 20.0)
    return array("h", (max(-32768, min(32767, round(value * factor))) for value in samples))


def _fit_bed(samples: array, target_samples: int) -> array:
    if not samples:
        raise ValueError("Bed contains no samples")
    repeats = (target_samples + len(samples) - 1) // len(samples)
    return array("h", (samples * repeats)[:target_samples])


def _music_excerpt(samples: array, target_samples: int, channels: int, sample_rate: int, rng: random.Random) -> tuple[array, float]:
    if not samples:
        raise ValueError("Music stem contains no samples")
    if len(samples) < target_samples:
        return _fit_bed(samples, target_samples), 0.0
    max_start_frame = (len(samples) - target_samples) // channels
    start_frame = rng.randint(0, max_start_frame)
    start = start_frame * channels
    return array("h", samples[start:start + target_samples]), start_frame / sample_rate


def generate(config: Config, recipe_id: str, seed: int, output_path: Path) -> GeneratedTrack:
    recipe = config.recipes[recipe_id]
    profile = config.profiles[recipe.profile_id]
    rng = random.Random(seed)

    beds = [
        item for item in config.assets
        if item.role == "Bed" and item.status == "Active"
        and (recipe.bed_family is None or item.family == recipe.bed_family)
    ]
    gestures = [
        item for item in config.assets
        if item.role == "Gesture" and item.status == "Active"
        and (recipe.gesture_family is None or item.family == recipe.gesture_family)
    ]
    if not beds or not gestures:
        raise ValueError(f"{recipe_id} has no eligible bed or gesture")

    bed = rng.choice(beds)
    gesture = rng.choice(gestures)
    total_frames = recipe.duration_sec * config.sample_rate
    target_samples = total_frames * config.channels
    mix = _fit_bed(_gain(_read_pcm(bed, config), profile.bed_gain_db), target_samples)
    gesture_samples = _gain(_read_pcm(gesture, config), profile.gesture_gain_db)

    earliest = profile.avoid_first_sec
    latest = max(earliest, recipe.duration_sec - profile.avoid_last_sec - len(gesture_samples) / config.channels / config.sample_rate)
    gesture_start_sec = rng.uniform(earliest, latest)

    music_stem = None
    music_start_sec = None
    if recipe.use_music_stem:
        music_stems = [
            item for item in config.assets
            if item.role == "Music" and item.status == "Active"
        ]
        music_stem = rng.choice(music_stems)
        music_samples, music_start_sec = _music_excerpt(
            _gain(_read_pcm(music_stem, config), profile.music_gain_db),
            target_samples,
            config.channels,
            config.sample_rate,
            rng,
        )
        for index, value in enumerate(music_samples):
            mix[index] = max(-32768, min(32767, mix[index] + value))

    start = int(gesture_start_sec * config.sample_rate) * config.channels
    for index, value in enumerate(gesture_samples[: max(0, target_samples - start)]):
        mixed = mix[start + index] + value
        mix[start + index] = max(-32768, min(32767, mixed))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as output:
        output.setnchannels(config.channels)
        output.setsampwidth(config.sample_width_bits // 8)
        output.setframerate(config.sample_rate)
        output.writeframes(mix.tobytes())

    return GeneratedTrack(
        output_path,
        seed,
        recipe_id,
        bed.asset_id,
        gesture.asset_id,
        gesture_start_sec,
        music_stem.asset_id if music_stem else None,
        music_start_sec,
    )
