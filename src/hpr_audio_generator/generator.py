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

    return GeneratedTrack(output_path, seed, recipe_id, bed.asset_id, gesture.asset_id, gesture_start_sec)

