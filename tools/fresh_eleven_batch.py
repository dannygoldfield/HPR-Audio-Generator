from __future__ import annotations

from array import array
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from math import log10, pow, sqrt
from pathlib import Path
import random
from shutil import copyfile
from tempfile import TemporaryDirectory
import wave

from hpr_audio_generator.config import Asset, Config, load_config
from hpr_audio_generator.delivery import measure_loop, measure_loudness, sha256, wav_duration
from hpr_audio_generator.generator import _read_pcm
from loop_native_lab import (
    _add_centered_music_event,
    _add_gesture,
    _calibrate_constant_gain,
    _periodic_texture,
)


DURATION_SEC = 11
BOUNDARY_MARGIN_SEC = 2.0
BASELINE_BED_RMS_DBFS = -32.0


def _active(config: Config, role: str) -> list[Asset]:
    return [asset for asset in config.assets if asset.role == role and asset.status == "Active"]


def _asset_duration_sec(asset: Asset) -> float:
    with wave.open(str(asset.path), "rb") as source:
        return source.getnframes() / source.getframerate()


def _duration_sec(samples: array, config: Config) -> float:
    return len(samples) / config.channels / config.sample_rate


def _normalize_rms(samples: array, target_dbfs: float) -> array:
    if not samples:
        raise ValueError("Cannot normalize an empty source")
    rms = sqrt(sum(value * value for value in samples) / len(samples))
    current_dbfs = 20.0 * log10(max(rms, 1.0) / 32768.0)
    factor = pow(10.0, (target_dbfs - current_dbfs) / 20.0)
    return array(
        "h",
        (max(-32768, min(32767, round(value * factor))) for value in samples),
    )


def _fresh_mix(
    config: Config,
    *,
    bed_asset: Asset,
    gesture_asset: Asset,
    music_asset: Asset,
    seed: int,
    output: Path,
    bed_target_dbfs: float = BASELINE_BED_RMS_DBFS,
) -> dict[str, object]:
    rng = random.Random(seed)
    frame_count = DURATION_SEC * config.sample_rate

    bed = _normalize_rms(_read_pcm(bed_asset, config), bed_target_dbfs)
    bed_max_start = max(0.0, _duration_sec(bed, config) - DURATION_SEC)
    bed_start_a = rng.uniform(0.0, bed_max_start)
    bed_start_b = rng.uniform(0.0, bed_max_start)
    if bed_max_start > DURATION_SEC and abs(bed_start_b - bed_start_a) < DURATION_SEC:
        bed_start_b = (bed_start_a + DURATION_SEC * 2.0) % bed_max_start
    mix = _periodic_texture(
        bed,
        frame_count=frame_count,
        channels=config.channels,
        sample_rate=config.sample_rate,
        source_start_sec=(bed_start_a, bed_start_b),
    )

    gesture = _normalize_rms(_read_pcm(gesture_asset, config), -40.0)
    gesture_duration = _duration_sec(gesture, config)
    latest_gesture = max(
        BOUNDARY_MARGIN_SEC,
        DURATION_SEC - BOUNDARY_MARGIN_SEC - gesture_duration,
    )
    gesture_start = rng.uniform(BOUNDARY_MARGIN_SEC, latest_gesture)
    _add_gesture(
        mix,
        gesture,
        start_sec=gesture_start,
        sample_rate=config.sample_rate,
        channels=config.channels,
    )

    music = _normalize_rms(_read_pcm(music_asset, config), -34.0)
    event_duration = rng.uniform(5.0, 6.5)
    event_start = (DURATION_SEC - event_duration) / 2.0
    music_max_start = max(0.0, _duration_sec(music, config) - event_duration)
    music_source_start = rng.uniform(0.0, music_max_start)
    music_fade = min(1.5, event_duration / 3.0)
    _add_centered_music_event(
        mix,
        music,
        source_start_sec=music_source_start,
        event_start_sec=event_start,
        event_duration_sec=event_duration,
        fade_sec=music_fade,
        sample_rate=config.sample_rate,
        channels=config.channels,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setnchannels(config.channels)
        target.setsampwidth(config.sample_width_bits // 8)
        target.setframerate(config.sample_rate)
        target.writeframes(mix.tobytes())
    return {
        "bed": {
            "id": bed_asset.asset_id,
            "sourceStartsSec": [round(bed_start_a, 6), round(bed_start_b, 6)],
        },
        "gesture": {
            "id": gesture_asset.asset_id,
            "startSec": round(gesture_start, 6),
        },
        "music": {
            "id": music_asset.asset_id,
            "sourceStartSec": round(music_source_start, 6),
            "eventStartSec": round(event_start, 6),
            "eventDurationSec": round(event_duration, 6),
            "fadeSec": round(music_fade, 6),
        },
    }


def build_batch(
    *,
    config_path: Path,
    output_root: Path,
    batch_id: str,
    count: int,
    base_seed: int,
    target_lufs: float,
) -> dict[str, object]:
    config = load_config(config_path)
    selector = random.Random(base_seed)
    beds = _active(config, "Bed")
    gestures = [
        asset
        for asset in _active(config, "Gesture")
        if _asset_duration_sec(asset) <= DURATION_SEC - 2 * BOUNDARY_MARGIN_SEC
    ]
    music = _active(config, "Music")
    selector.shuffle(beds)
    selector.shuffle(gestures)
    selector.shuffle(music)
    available_combinations = min(len(beds), len(gestures), len(music))
    if available_combinations < count:
        raise ValueError("Not enough unique active assets for the requested batch")

    batch_root = output_root / batch_id
    raw_root = batch_root / "raw"
    batch_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()
    candidates = []
    delivery_rejections = []
    asset_cursor = 0
    while len(candidates) < count:
        if asset_cursor >= available_combinations:
            raise ValueError(
                "Exhausted unique ingredient combinations before finding enough "
                "candidates that satisfy the loudness and true-peak requirements"
            )
        position = len(candidates) + 1
        seed = base_seed + asset_cursor
        bed_asset = beds[asset_cursor]
        gesture_asset = gestures[asset_cursor]
        music_asset = music[asset_cursor]
        asset_cursor += 1
        identity = f"fresh-11|{batch_id}|{seed}|{bed_asset.asset_id}|{gesture_asset.asset_id}|{music_asset.asset_id}"
        audio_id = "AUD-11S-" + hashlib.sha256(identity.encode()).hexdigest()[:10].upper()
        raw_path = raw_root / f"{audio_id}.raw.wav"
        output_path = batch_root / f"{audio_id}.wav"
        manifest_path = batch_root / f"{audio_id}.json"
        with TemporaryDirectory(prefix=f"candidate-{position:02d}-", dir=batch_root) as work:
            work_root = Path(work)
            working_raw = work_root / "raw.wav"
            working_output = work_root / "delivered.wav"
            ingredients = _fresh_mix(
                config,
                bed_asset=bed_asset,
                gesture_asset=gesture_asset,
                music_asset=music_asset,
                seed=seed,
                output=working_raw,
            )
            raw_loudness = measure_loudness(working_raw)
            gain_db, delivered = _calibrate_constant_gain(
                working_raw,
                working_output,
                target_lufs=target_lufs,
            )
            if delivered.integrated_lufs < target_lufs - 0.2:
                delivery_rejections.append(
                    {
                        "seed": seed,
                        "bed": bed_asset.asset_id,
                        "gesture": gesture_asset.asset_id,
                        "music": music_asset.asset_id,
                        "deliveredIntegratedLufs": delivered.integrated_lufs,
                        "deliveredTruePeakDbfs": delivered.true_peak_dbfs,
                        "reason": "target loudness would require exceeding the true-peak ceiling",
                    }
                )
                continue
            copyfile(working_raw, raw_path)
            copyfile(working_output, output_path)
        loop = measure_loop(output_path)
        manifest = {
            "schemaVersion": "1.0",
            "candidateType": "audio",
            "audioId": audio_id,
            "batchId": batch_id,
            "reviewPosition": position,
            "recipeId": "AR-012",
            "generatorVersion": f"{config.generator_version}-fresh-11-lab-1",
            "durationSec": wav_duration(output_path),
            "durationBank": "11s",
            "seed": seed,
            "comparisonName": f"Fresh 11-second option {position:02d}",
            "designLineage": {
                "relationshipToSevenSecondBank": "none; independently selected and composed",
                "nativeDurationSec": DURATION_SEC,
            },
            "ingredients": ingredients,
            "loopNativeStructure": {
                "ambient": "two Hann-windowed grains, half-cycle offset, circular overlap-add",
                "eventsInsideBoundary": True,
                "boundaryMarginSec": BOUNDARY_MARGIN_SEC,
                "musicTreatment": "finite centered event; no music crosses or restarts at boundary",
                "crossfadeRepair": False,
                "extendedFromShorterTrack": False,
            },
            "delivery": {
                "method": "constant gain only",
                "targetLufs": target_lufs,
                "rawIntegratedLufs": raw_loudness.integrated_lufs,
                "gainDb": round(gain_db, 3),
                "deliveredIntegratedLufs": delivered.integrated_lufs,
                "deliveredTruePeakDbfs": delivered.true_peak_dbfs,
                "compression": False,
                "limiting": False,
            },
            "loopValidation": {
                **asdict(loop),
                "structurallyPeriodicAmbient": True,
                "eventsClearBoundary": True,
                "humanAuditionRequired": True,
            },
            "format": {
                "container": "WAV",
                "sampleRate": config.sample_rate,
                "channels": config.channels,
                "sampleWidthBits": config.sample_width_bits,
                "nativeDuration": True,
            },
            "output": {"path": str(output_path.resolve()), "sha256": sha256(output_path)},
            "createdAt": created_at,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        candidates.append(
            {
                "audioId": audio_id,
                "seed": seed,
                "audio": str(output_path.resolve()),
                "manifest": str(manifest_path.resolve()),
                "loudnessLufs": delivered.integrated_lufs,
                "loopValidation": "structural pass; human review required",
            }
        )
    batch = {
        "schemaVersion": "1.0",
        "candidateType": "audio_review_batch",
        "batchId": batch_id,
        "recipeId": "AR-012",
        "generatorVersion": f"{config.generator_version}-fresh-11-lab-1",
        "candidateCount": len(candidates),
        "durationSec": DURATION_SEC,
        "durationBank": "11s",
        "registrationStatus": "ready_for_review",
        "baseSeed": base_seed,
        "requirements": {
            "audioOnlyReview": True,
            "independentDurationFamily": True,
            "extendedFromSevenSeconds": False,
            "uniqueAssetsWithinBatch": True,
            "humanLoopApprovalRequired": True,
        },
        "deliveryRejectedCombinations": delivery_rejections,
        "candidates": candidates,
        "createdAt": created_at,
    }
    (batch_root / "batch-manifest.json").write_text(
        json.dumps(batch, indent=2) + "\n", encoding="utf-8"
    )
    return batch


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a fresh independent eleven-second audio batch")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--base-seed", type=int, required=True)
    parser.add_argument("--target-lufs", type=float, default=-22.0)
    args = parser.parse_args()
    result = build_batch(
        config_path=args.config,
        output_root=args.output_root,
        batch_id=args.batch_id,
        count=args.count,
        base_seed=args.base_seed,
        target_lufs=args.target_lufs,
    )
    print(f"Built {result['candidateCount']} fresh native eleven-second candidates")


if __name__ == "__main__":
    main()
