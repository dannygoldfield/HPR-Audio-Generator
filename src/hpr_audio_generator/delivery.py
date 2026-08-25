from __future__ import annotations

from array import array
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from math import log10, sqrt
from pathlib import Path
import re
import shutil
import subprocess
import wave

from .config import Config
from .generator import GeneratedTrack, generate


LOUDNESS_RE = re.compile(r"I:\s+(-?\d+(?:\.\d+)?) LUFS")
TRUE_PEAK_RE = re.compile(r"Peak:\s+(-?\d+(?:\.\d+)?) dBFS")


@dataclass(frozen=True)
class LoudnessMeasurement:
    integrated_lufs: float
    true_peak_dbfs: float


@dataclass(frozen=True)
class LoopMeasurement:
    seam_step: int
    ordinary_step_p999: int
    edge_delta_db: float
    click_check_passed: bool


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def delivery_gain_db(measured_lufs: float, target_lufs: float) -> float:
    return target_lufs - measured_lufs


def measure_loudness(path: Path, *, ffmpeg: str = "ffmpeg") -> LoudnessMeasurement:
    if shutil.which(ffmpeg) is None:
        raise RuntimeError(f"Required audio tool is unavailable: {ffmpeg}")
    completed = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    output = completed.stderr + completed.stdout
    loudness = LOUDNESS_RE.findall(output)
    true_peak = TRUE_PEAK_RE.findall(output)
    if completed.returncode or not loudness or not true_peak:
        raise RuntimeError(f"Could not measure loudness for {path}: {output[-1000:]}")
    return LoudnessMeasurement(float(loudness[-1]), float(true_peak[-1]))


def apply_constant_gain(
    source: Path,
    output: Path,
    gain_db: float,
    *,
    ffmpeg: str = "ffmpeg",
) -> None:
    if shutil.which(ffmpeg) is None:
        raise RuntimeError(f"Required audio tool is unavailable: {ffmpeg}")
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(source),
            "-af",
            f"volume={gain_db:.6f}dB",
            "-c:a",
            "pcm_s16le",
            str(output),
        ],
        check=True,
    )


def _percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def _rms(values: list[int]) -> float:
    return sqrt(sum(value * value for value in values) / max(1, len(values)))


def _db_ratio(first: float, second: float) -> float:
    return 20 * log10(max(first, 1.0) / max(second, 1.0))


def measure_loop(path: Path) -> LoopMeasurement:
    with wave.open(str(path), "rb") as audio:
        channels = audio.getnchannels()
        sample_rate = audio.getframerate()
        samples = array("h")
        samples.frombytes(audio.readframes(audio.getnframes()))
    frames = [
        samples[index : index + channels]
        for index in range(0, len(samples), channels)
    ]
    if len(frames) < 2:
        raise ValueError("Audio candidate is too short to inspect its loop")
    ordinary_steps = [
        max(abs(current[channel] - previous[channel]) for channel in range(channels))
        for previous, current in zip(frames, frames[1:])
    ]
    seam_step = max(
        abs(frames[0][channel] - frames[-1][channel])
        for channel in range(channels)
    )
    p999 = _percentile(ordinary_steps, 0.999)
    edge_frames = max(1, round(sample_rate * 0.05))
    head = [sample for frame in frames[:edge_frames] for sample in frame]
    tail = [sample for frame in frames[-edge_frames:] for sample in frame]
    edge_delta_db = abs(_db_ratio(_rms(head), _rms(tail)))
    return LoopMeasurement(
        seam_step=seam_step,
        ordinary_step_p999=p999,
        edge_delta_db=round(edge_delta_db, 3),
        click_check_passed=seam_step <= max(1, p999),
    )


def _audio_id(config: Config, recipe_id: str, seed: int, target_lufs: float) -> str:
    identity = f"{config.generator_version}|{recipe_id}|{seed}|{target_lufs:.1f}"
    return "AUD-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12].upper()


def _ingredient_manifest(track: GeneratedTrack) -> dict[str, object]:
    return {
        "bed": {"id": track.bed_id, "startSec": 0.0},
        "gesture": {
            "id": track.gesture_id,
            "startSec": round(track.gesture_start_sec, 6),
        },
        "music": (
            {
                "id": track.music_stem_id,
                "startSec": round(track.music_start_sec or 0.0, 6),
            }
            if track.music_stem_id
            else None
        ),
    }


def render_review_batch(
    config: Config,
    *,
    recipe_id: str,
    seeds: list[int],
    batch_id: str,
    output_root: Path,
    target_lufs: float = -22.0,
    true_peak_ceiling_dbfs: float = -1.0,
) -> dict[str, object]:
    if recipe_id not in config.recipes:
        raise ValueError(f"Unknown recipe: {recipe_id}")
    recipe = config.recipes[recipe_id]
    batch_root = output_root / batch_id
    raw_root = batch_root / "raw"
    batch_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    candidates: list[dict[str, object]] = []
    created_at = datetime.now(timezone.utc).isoformat()

    for position, seed in enumerate(seeds, start=1):
        audio_id = _audio_id(config, recipe_id, seed, target_lufs)
        raw_path = raw_root / f"{audio_id}.raw.wav"
        output_path = batch_root / f"{audio_id}.wav"
        manifest_path = batch_root / f"{audio_id}.json"
        generated = generate(config, recipe_id, seed, raw_path)
        raw_loudness = measure_loudness(raw_path)
        gain_db = delivery_gain_db(raw_loudness.integrated_lufs, target_lufs)
        projected_peak = raw_loudness.true_peak_dbfs + gain_db
        if projected_peak > true_peak_ceiling_dbfs:
            raise ValueError(
                f"{audio_id} would exceed the transparent true-peak ceiling: "
                f"{projected_peak:.1f} dBFS"
            )
        apply_constant_gain(raw_path, output_path, gain_db)
        delivered_loudness = measure_loudness(output_path)
        loop = measure_loop(output_path)
        duration = wav_duration(output_path)
        if abs(duration - recipe.duration_sec) > 1 / config.sample_rate:
            raise ValueError(f"{audio_id} has unexpected duration: {duration}")
        if abs(delivered_loudness.integrated_lufs - target_lufs) > 0.2:
            raise ValueError(
                f"{audio_id} missed delivery loudness: "
                f"{delivered_loudness.integrated_lufs} LUFS"
            )
        if not loop.click_check_passed:
            raise ValueError(f"{audio_id} has a suspicious sample discontinuity")

        manifest: dict[str, object] = {
            "schemaVersion": "1.0",
            "candidateType": "audio",
            "audioId": audio_id,
            "batchId": batch_id,
            "reviewPosition": position,
            "recipeId": recipe_id,
            "generatorVersion": config.generator_version,
            "durationSec": duration,
            "seed": seed,
            "referenceLineage": {
                "batchId": "AB-20260731-003",
                "recipeId": "AR-007",
                "relationship": "same recipe family and seed; duration changed from 7 to 11 seconds",
            },
            "ingredients": _ingredient_manifest(generated),
            "delivery": {
                "method": "constant gain only",
                "targetLufs": target_lufs,
                "rawIntegratedLufs": raw_loudness.integrated_lufs,
                "gainDb": round(gain_db, 3),
                "deliveredIntegratedLufs": delivered_loudness.integrated_lufs,
                "deliveredTruePeakDbfs": delivered_loudness.true_peak_dbfs,
                "compression": False,
                "limiting": False,
            },
            "loopValidation": {
                **asdict(loop),
                "continuousPlaybackRequired": True,
                "humanAuditionRequired": True,
            },
            "format": {
                "container": "WAV",
                "sampleRate": config.sample_rate,
                "channels": config.channels,
                "sampleWidthBits": config.sample_width_bits,
                "nativeDuration": True,
            },
            "raw": {"path": str(raw_path.resolve()), "sha256": sha256(raw_path)},
            "output": {
                "path": str(output_path.resolve()),
                "sha256": sha256(output_path),
            },
            "createdAt": created_at,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        candidates.append(
            {
                "audioId": audio_id,
                "seed": seed,
                "audio": str(output_path.resolve()),
                "manifest": str(manifest_path.resolve()),
                "loudnessLufs": delivered_loudness.integrated_lufs,
                "loopClickCheck": "pass",
            }
        )

    batch_manifest: dict[str, object] = {
        "schemaVersion": "1.0",
        "candidateType": "audio_review_batch",
        "batchId": batch_id,
        "recipeId": recipe_id,
        "generatorVersion": config.generator_version,
        "candidateCount": len(candidates),
        "durationSec": recipe.duration_sec,
        "targetLufs": target_lufs,
        "sourceReferenceBatch": "AB-20260731-003",
        "requirements": {
            "audioOnlyReview": True,
            "invisibleLoop": True,
            "noTimeStretch": True,
            "noRepeatedSevenSecondMix": True,
            "deliveryProcessing": "constant gain only",
        },
        "candidates": candidates,
        "createdAt": created_at,
    }
    (batch_root / "batch-manifest.json").write_text(
        json.dumps(batch_manifest, indent=2) + "\n", encoding="utf-8"
    )
    return batch_manifest
