from __future__ import annotations

from array import array
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from math import cos, pi, sin
from pathlib import Path
import wave

from hpr_audio_generator.config import Asset, Config, load_config
from hpr_audio_generator.delivery import (
    apply_constant_gain,
    delivery_gain_db,
    measure_loop,
    measure_loudness,
    sha256,
    wav_duration,
)
from hpr_audio_generator.generator import _gain, _read_pcm


VARIANTS = (
    {
        "id": "LR-001",
        "name": "Locked sound — 1.5-second equal-power join",
        "joinSec": 1.5,
        "excerptMode": "locked",
    },
    {
        "id": "LR-002",
        "name": "Locked sound — 2.5-second equal-power join",
        "joinSec": 2.5,
        "excerptMode": "locked",
    },
    {
        "id": "LR-003",
        "name": "Same assets — seam-aware 2-second join",
        "joinSec": 2.0,
        "excerptMode": "seam-aware",
    },
)


def _asset(config: Config, asset_id: str) -> Asset:
    for item in config.assets:
        if item.asset_id == asset_id:
            return item
    raise ValueError(f"Unknown asset: {asset_id}")


def _fit(samples: array, required_samples: int) -> array:
    if not samples:
        raise ValueError("Source contains no samples")
    repeats = (required_samples + len(samples) - 1) // len(samples)
    return array("h", (samples * repeats)[:required_samples])


def _excerpt(
    samples: array,
    *,
    start_sec: float,
    required_samples: int,
    channels: int,
    sample_rate: int,
) -> array:
    start = round(start_sec * sample_rate) * channels
    if start + required_samples <= len(samples):
        return array("h", samples[start : start + required_samples])
    wrapped = array("h", samples[start:])
    wrapped.extend(_fit(samples, required_samples - len(wrapped)))
    return wrapped


def _best_excerpt(
    samples: array,
    *,
    target_samples: int,
    fade_samples: int,
    channels: int,
    sample_rate: int,
    step_sec: float = 0.25,
) -> tuple[array, float]:
    required_samples = target_samples + fade_samples
    if len(samples) < required_samples:
        return _fit(samples, required_samples), 0.0
    max_start_frame = (len(samples) - required_samples) // channels
    step_frames = max(1, round(step_sec * sample_rate))
    starts = list(range(0, max_start_frame + 1, step_frames))
    if starts[-1] != max_start_frame:
        starts.append(max_start_frame)
    stride = channels * 128

    def cost(start_frame: int) -> float:
        start = start_frame * channels
        continuation = start + target_samples
        squared_error = 0.0
        signal_energy = 1.0
        for offset in range(0, fade_samples, stride):
            for channel in range(channels):
                head = samples[start + offset + channel]
                tail = samples[continuation + offset + channel]
                difference = head - tail
                squared_error += difference * difference
                signal_energy += head * head + tail * tail
        return squared_error / signal_energy

    start_frame = min(starts, key=cost)
    start = start_frame * channels
    return (
        array("h", samples[start : start + required_samples]),
        start_frame / sample_rate,
    )


def _equal_power_loop(
    samples: array,
    *,
    target_samples: int,
    fade_frames: int,
    channels: int,
) -> array:
    fade_samples = fade_frames * channels
    if len(samples) < target_samples + fade_samples:
        raise ValueError("Continuous layer is too short for the requested join")
    result = array("h", samples[:target_samples])
    denominator = max(1, fade_frames - 1)
    for frame in range(fade_frames):
        progress = frame / denominator
        continuation_weight = cos(progress * pi / 2.0)
        beginning_weight = sin(progress * pi / 2.0)
        beginning = frame * channels
        continuation = target_samples + beginning
        for channel in range(channels):
            value = round(
                samples[continuation + channel] * continuation_weight
                + samples[beginning + channel] * beginning_weight
            )
            result[beginning + channel] = max(-32768, min(32767, value))
    result[fade_samples:] = samples[fade_samples:target_samples]
    return result


def _mix_variant(
    config: Config,
    source: dict[str, object],
    variant: dict[str, object],
    output: Path,
) -> dict[str, float]:
    profile = config.profiles[config.recipes[source["recipeId"]].profile_id]
    duration_sec = float(source["durationSec"])
    target_frames = round(duration_sec * config.sample_rate)
    target_samples = target_frames * config.channels
    fade_frames = round(float(variant["joinSec"]) * config.sample_rate)
    fade_samples = fade_frames * config.channels
    required_samples = target_samples + fade_samples
    ingredients = source["ingredients"]

    bed_info = ingredients["bed"]
    bed = _gain(_read_pcm(_asset(config, bed_info["id"]), config), profile.bed_gain_db)
    if variant["excerptMode"] == "seam-aware":
        bed_source, bed_start = _best_excerpt(
            bed,
            target_samples=target_samples,
            fade_samples=fade_samples,
            channels=config.channels,
            sample_rate=config.sample_rate,
        )
    else:
        bed_start = float(bed_info.get("startSec", 0.0))
        bed_source = _excerpt(
            bed,
            start_sec=bed_start,
            required_samples=required_samples,
            channels=config.channels,
            sample_rate=config.sample_rate,
        )
    mix = _equal_power_loop(
        bed_source,
        target_samples=target_samples,
        fade_frames=fade_frames,
        channels=config.channels,
    )

    music_info = ingredients.get("music")
    music_start = 0.0
    if music_info:
        music = _gain(
            _read_pcm(_asset(config, music_info["id"]), config),
            profile.music_gain_db,
        )
        if variant["excerptMode"] == "seam-aware":
            music_source, music_start = _best_excerpt(
                music,
                target_samples=target_samples,
                fade_samples=fade_samples,
                channels=config.channels,
                sample_rate=config.sample_rate,
            )
        else:
            music_start = float(music_info["startSec"])
            music_source = _excerpt(
                music,
                start_sec=music_start,
                required_samples=required_samples,
                channels=config.channels,
                sample_rate=config.sample_rate,
            )
        looped_music = _equal_power_loop(
            music_source,
            target_samples=target_samples,
            fade_frames=fade_frames,
            channels=config.channels,
        )
        for index, value in enumerate(looped_music):
            mix[index] = max(-32768, min(32767, mix[index] + value))

    gesture_info = ingredients["gesture"]
    gesture = _gain(
        _read_pcm(_asset(config, gesture_info["id"]), config),
        profile.gesture_gain_db,
    )
    gesture_start = float(gesture_info["startSec"])
    start = round(gesture_start * config.sample_rate) * config.channels
    for index, value in enumerate(gesture[: max(0, target_samples - start)]):
        mix[start + index] = max(-32768, min(32767, mix[start + index] + value))

    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setnchannels(config.channels)
        target.setsampwidth(config.sample_width_bits // 8)
        target.setframerate(config.sample_rate)
        target.writeframes(mix.tobytes())
    return {
        "bedStartSec": bed_start,
        "musicStartSec": music_start,
        "gestureStartSec": gesture_start,
    }


def build_lab(
    *,
    config_path: Path,
    source_manifest_path: Path,
    output_root: Path,
    batch_id: str,
    target_lufs: float,
) -> dict[str, object]:
    config = load_config(config_path)
    source = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source_audio_id = source["audioId"]
    batch_root = output_root / batch_id
    raw_root = batch_root / "raw"
    batch_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()
    candidates = []

    for position, variant in enumerate(VARIANTS, start=1):
        identity = f"{source_audio_id}|{variant['id']}|{variant['joinSec']}|{variant['excerptMode']}|{target_lufs}"
        audio_id = "AUD-LR-" + hashlib.sha256(identity.encode()).hexdigest()[:10].upper()
        raw_path = raw_root / f"{audio_id}.raw.wav"
        output_path = batch_root / f"{audio_id}.wav"
        manifest_path = batch_root / f"{audio_id}.json"
        starts = _mix_variant(config, source, variant, raw_path)
        raw_loudness = measure_loudness(raw_path)
        gain_db = delivery_gain_db(raw_loudness.integrated_lufs, target_lufs)
        apply_constant_gain(raw_path, output_path, gain_db)
        delivered = measure_loudness(output_path)
        loop = measure_loop(output_path)
        manifest = {
            "schemaVersion": "1.0",
            "candidateType": "audio",
            "audioId": audio_id,
            "batchId": batch_id,
            "reviewPosition": position,
            "recipeId": "AR-008-LOOP-REPAIR",
            "generatorVersion": f"{config.generator_version}-loop-lab-1",
            "durationSec": wav_duration(output_path),
            "seed": source["seed"],
            "comparisonName": variant["name"],
            "sourceAudioId": source_audio_id,
            "soundDesignState": "approved; ingredients and gains locked",
            "loopRepair": {
                "variantId": variant["id"],
                "joinSec": variant["joinSec"],
                "joinCurve": "equal-power",
                "excerptMode": variant["excerptMode"],
                "sourcePositions": starts,
            },
            "ingredients": source["ingredients"],
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
                "previousTechnicalCheckInvalidatedByHumanReview": True,
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
                "seed": source["seed"],
                "audio": str(output_path.resolve()),
                "manifest": str(manifest_path.resolve()),
                "loudnessLufs": delivered.integrated_lufs,
                "loopClickCheck": "human review required",
            }
        )

    batch = {
        "schemaVersion": "1.0",
        "candidateType": "audio_review_batch",
        "batchId": batch_id,
        "recipeId": "AR-008-LOOP-REPAIR",
        "generatorVersion": f"{config.generator_version}-loop-lab-1",
        "candidateCount": len(candidates),
        "durationSec": source["durationSec"],
        "targetLufs": target_lufs,
        "sourceReferenceBatch": source["batchId"],
        "sourceAudioId": source_audio_id,
        "requirements": {
            "audioOnlyReview": True,
            "loopRepairComparison": True,
            "soundDesignLocked": True,
            "humanLoopApprovalRequired": True,
        },
        "candidates": candidates,
        "createdAt": created_at,
    }
    (batch_root / "batch-manifest.json").write_text(
        json.dumps(batch, indent=2) + "\n", encoding="utf-8"
    )
    return batch


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a small human loop-repair comparison")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--target-lufs", type=float, default=-22.0)
    args = parser.parse_args()
    result = build_lab(
        config_path=args.config,
        source_manifest_path=args.source_manifest,
        output_root=args.output_root,
        batch_id=args.batch_id,
        target_lufs=args.target_lufs,
    )
    print(f"Built {result['candidateCount']} loop-repair candidates in {args.output_root / args.batch_id}")


if __name__ == "__main__":
    main()
