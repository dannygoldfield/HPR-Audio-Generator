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
        "id": "LN-001",
        "name": "Diagnostic A — loop-native rain and birds only",
        "gesture": False,
        "music": False,
    },
    {
        "id": "LN-002",
        "name": "Diagnostic B — add the approved drawer gesture",
        "gesture": True,
        "music": False,
    },
    {
        "id": "LN-003",
        "name": "Candidate C — add music as a centered event",
        "gesture": True,
        "music": True,
    },
)


def _calibrate_constant_gain(
    raw_path: Path,
    output_path: Path,
    *,
    target_lufs: float,
    true_peak_ceiling_dbfs: float = -1.0,
) -> tuple[float, object]:
    raw = measure_loudness(raw_path)
    total_gain = min(
        delivery_gain_db(raw.integrated_lufs, target_lufs),
        true_peak_ceiling_dbfs - raw.true_peak_dbfs,
    )
    for _ in range(8):
        apply_constant_gain(raw_path, output_path, total_gain)
        delivered = measure_loudness(output_path)
        desired = target_lufs - delivered.integrated_lufs
        peak_room = true_peak_ceiling_dbfs - delivered.true_peak_dbfs
        correction = min(desired, peak_room)
        if abs(correction) <= 0.05:
            return total_gain, delivered
        total_gain += correction
    return total_gain, delivered


def _asset(config: Config, asset_id: str) -> Asset:
    for item in config.assets:
        if item.asset_id == asset_id:
            return item
    raise ValueError(f"Unknown asset: {asset_id}")


def _source_excerpt(
    samples: array,
    *,
    start_frame: int,
    frame_count: int,
    channels: int,
) -> array:
    required = frame_count * channels
    start = start_frame * channels
    if start + required <= len(samples):
        return array("h", samples[start : start + required])
    if not samples:
        raise ValueError("Source contains no samples")
    result = array("h", samples[start:])
    while len(result) < required:
        result.extend(samples[: min(len(samples), required - len(result))])
    return result


def _periodic_texture(
    samples: array,
    *,
    frame_count: int,
    channels: int,
    sample_rate: int,
    source_start_sec: tuple[float, float],
) -> array:
    """Overlap two tapered source grains into a continuous circular texture."""
    accum = [0.0] * (frame_count * channels)
    weights = [0.0] * frame_count
    denominator = max(1, frame_count - 1)
    for grain_index, source_sec in enumerate(source_start_sec):
        grain = _source_excerpt(
            samples,
            start_frame=round(source_sec * sample_rate),
            frame_count=frame_count,
            channels=channels,
        )
        output_offset = grain_index * frame_count // 2
        for local_frame in range(frame_count):
            weight = 0.5 - 0.5 * cos(2.0 * pi * local_frame / denominator)
            output_frame = (output_offset + local_frame) % frame_count
            weights[output_frame] += weight
            output = output_frame * channels
            source = local_frame * channels
            for channel in range(channels):
                accum[output + channel] += grain[source + channel] * weight
    result = array("h")
    for frame in range(frame_count):
        weight = max(weights[frame], 1e-9)
        start = frame * channels
        for channel in range(channels):
            value = round(accum[start + channel] / weight)
            result.append(max(-32768, min(32767, value)))
    return result


def _add_gesture(
    mix: array,
    gesture: array,
    *,
    start_sec: float,
    sample_rate: int,
    channels: int,
) -> None:
    start = round(start_sec * sample_rate) * channels
    for index, value in enumerate(gesture[: max(0, len(mix) - start)]):
        mix[start + index] = max(-32768, min(32767, mix[start + index] + value))


def _add_centered_music_event(
    mix: array,
    music: array,
    *,
    source_start_sec: float,
    event_start_sec: float,
    event_duration_sec: float,
    fade_sec: float,
    sample_rate: int,
    channels: int,
) -> None:
    event_frames = round(event_duration_sec * sample_rate)
    fade_frames = round(fade_sec * sample_rate)
    excerpt = _source_excerpt(
        music,
        start_frame=round(source_start_sec * sample_rate),
        frame_count=event_frames,
        channels=channels,
    )
    output_start = round(event_start_sec * sample_rate) * channels
    for frame in range(event_frames):
        if frame < fade_frames:
            weight = sin((frame / max(1, fade_frames - 1)) * pi / 2.0)
        elif frame >= event_frames - fade_frames:
            remaining = event_frames - 1 - frame
            weight = sin((remaining / max(1, fade_frames - 1)) * pi / 2.0)
        else:
            weight = 1.0
        for channel in range(channels):
            output = output_start + frame * channels + channel
            source = frame * channels + channel
            mix[output] = max(
                -32768,
                min(32767, mix[output] + round(excerpt[source] * weight)),
            )


def _mix_variant(
    config: Config,
    source: dict[str, object],
    variant: dict[str, object],
    output: Path,
) -> None:
    profile = config.profiles[config.recipes[source["recipeId"]].profile_id]
    frame_count = round(float(source["durationSec"]) * config.sample_rate)
    ingredients = source["ingredients"]
    bed = _gain(
        _read_pcm(_asset(config, ingredients["bed"]["id"]), config),
        profile.bed_gain_db,
    )
    mix = _periodic_texture(
        bed,
        frame_count=frame_count,
        channels=config.channels,
        sample_rate=config.sample_rate,
        source_start_sec=(0.0, 30.0),
    )
    if variant["gesture"]:
        gesture = _gain(
            _read_pcm(_asset(config, ingredients["gesture"]["id"]), config),
            profile.gesture_gain_db,
        )
        _add_gesture(
            mix,
            gesture,
            start_sec=float(ingredients["gesture"]["startSec"]),
            sample_rate=config.sample_rate,
            channels=config.channels,
        )
    if variant["music"]:
        music = _gain(
            _read_pcm(_asset(config, ingredients["music"]["id"]), config),
            profile.music_gain_db,
        )
        _add_centered_music_event(
            mix,
            music,
            source_start_sec=float(ingredients["music"]["startSec"]),
            event_start_sec=2.0,
            event_duration_sec=7.0,
            fade_sec=1.5,
            sample_rate=config.sample_rate,
            channels=config.channels,
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output), "wb") as target:
        target.setnchannels(config.channels)
        target.setsampwidth(config.sample_width_bits // 8)
        target.setframerate(config.sample_rate)
        target.writeframes(mix.tobytes())


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
        identity = f"{source_audio_id}|{variant['id']}|loop-native-1|{target_lufs}"
        audio_id = "AUD-LN-" + hashlib.sha256(identity.encode()).hexdigest()[:10].upper()
        raw_path = raw_root / f"{audio_id}.raw.wav"
        output_path = batch_root / f"{audio_id}.wav"
        manifest_path = batch_root / f"{audio_id}.json"
        _mix_variant(config, source, variant, raw_path)
        raw_loudness = measure_loudness(raw_path)
        gain_db, delivered = _calibrate_constant_gain(
            raw_path,
            output_path,
            target_lufs=target_lufs,
        )
        loop = measure_loop(output_path)
        manifest = {
            "schemaVersion": "1.0",
            "candidateType": "audio",
            "audioId": audio_id,
            "batchId": batch_id,
            "reviewPosition": position,
            "recipeId": "AR-008-LOOP-NATIVE",
            "generatorVersion": f"{config.generator_version}-loop-native-lab-1",
            "durationSec": wav_duration(output_path),
            "seed": source["seed"],
            "comparisonName": variant["name"],
            "sourceAudioId": source_audio_id,
            "soundDesignState": "approved source ingredients",
            "loopNativeStructure": {
                "ambient": "two Hann-windowed grains, half-cycle offset, circular overlap-add",
                "ambientSourceStartsSec": [0.0, 30.0],
                "gestureIncluded": variant["gesture"],
                "musicIncluded": variant["music"],
                "musicTreatment": "centered seven-second event with 1.5-second entrance and exit" if variant["music"] else None,
                "boundaryTreatment": "ambient continuity only; no event crosses or restarts at boundary",
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
                "crossfadeRepair": False,
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
        "recipeId": "AR-008-LOOP-NATIVE",
        "generatorVersion": f"{config.generator_version}-loop-native-lab-1",
        "candidateCount": len(candidates),
        "durationSec": source["durationSec"],
        "targetLufs": target_lufs,
        "sourceReferenceBatch": source["batchId"],
        "sourceAudioId": source_audio_id,
        "requirements": {
            "audioOnlyReview": True,
            "loopNativeDiagnostic": True,
            "crossfadeRepairRejected": True,
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
    parser = argparse.ArgumentParser(description="Build a layer-isolated loop-native audio comparison")
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
    print(f"Built {result['candidateCount']} loop-native candidates in {args.output_root / args.batch_id}")


if __name__ == "__main__":
    main()
