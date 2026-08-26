from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from hpr_audio_generator.config import Asset, Config, load_config
from hpr_audio_generator.delivery import measure_loop, measure_loudness, sha256, wav_duration
from fresh_eleven_batch import BASELINE_BED_RMS_DBFS, _fresh_mix
from loop_native_lab import _calibrate_constant_gain


BED_OFFSETS_DB = (-1.5, -2.5, -3.5)


def _asset(config: Config, asset_id: str) -> Asset:
    for asset in config.assets:
        if asset.asset_id == asset_id:
            return asset
    raise ValueError(f"Unknown asset: {asset_id}")


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
    if source.get("recipeId") != "AR-012":
        raise ValueError("Bed calibration requires a fresh native eleven-second source")
    source_ingredients = source["ingredients"]
    bed_asset = _asset(config, source_ingredients["bed"]["id"])
    gesture_asset = _asset(config, source_ingredients["gesture"]["id"])
    music_asset = _asset(config, source_ingredients["music"]["id"])

    batch_root = output_root / batch_id
    raw_root = batch_root / "raw"
    batch_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc).isoformat()
    candidates = []
    for position, bed_offset_db in enumerate(BED_OFFSETS_DB, start=1):
        identity = (
            f"{source['audioId']}|bed-balance|{bed_offset_db}|{target_lufs}"
        )
        audio_id = "AUD-BED-" + hashlib.sha256(identity.encode()).hexdigest()[:10].upper()
        raw_path = raw_root / f"{audio_id}.raw.wav"
        output_path = batch_root / f"{audio_id}.wav"
        manifest_path = batch_root / f"{audio_id}.json"
        ingredients = _fresh_mix(
            config,
            bed_asset=bed_asset,
            gesture_asset=gesture_asset,
            music_asset=music_asset,
            seed=int(source["seed"]),
            output=raw_path,
            bed_target_dbfs=BASELINE_BED_RMS_DBFS + bed_offset_db,
        )
        if ingredients != source_ingredients:
            raise ValueError("Calibration changed something besides the bed level")
        raw_loudness = measure_loudness(raw_path)
        gain_db, delivered = _calibrate_constant_gain(
            raw_path,
            output_path,
            target_lufs=target_lufs,
        )
        if delivered.integrated_lufs < target_lufs - 0.2:
            raise ValueError(
                f"{audio_id} cannot reach {target_lufs} LUFS below the peak ceiling"
            )
        loop = measure_loop(output_path)
        manifest = {
            "schemaVersion": "1.0",
            "candidateType": "audio",
            "audioId": audio_id,
            "batchId": batch_id,
            "reviewPosition": position,
            "recipeId": "AR-012-BED-BALANCE",
            "generatorVersion": f"{config.generator_version}-bed-balance-lab-1",
            "durationSec": wav_duration(output_path),
            "durationBank": "11s",
            "seed": int(source["seed"]),
            "comparisonName": f"Bed {abs(bed_offset_db):.1f} dB lower",
            "sourceAudioId": source["audioId"],
            "ingredients": ingredients,
            "balanceChange": {
                "changedLayer": "continuous bed only",
                "bedOffsetDb": bed_offset_db,
                "gestureOffsetDb": 0.0,
                "musicOffsetDb": 0.0,
                "overallPlaybackTargetUnchanged": True,
            },
            "loopNativeStructure": source["loopNativeStructure"],
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
                "sourceLoopHumanApproved": True,
                "sampleAccuratePlayerRequired": True,
            },
            "format": source["format"],
            "output": {"path": str(output_path.resolve()), "sha256": sha256(output_path)},
            "createdAt": created_at,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        candidates.append(
            {
                "audioId": audio_id,
                "seed": int(source["seed"]),
                "audio": str(output_path.resolve()),
                "manifest": str(manifest_path.resolve()),
                "loudnessLufs": delivered.integrated_lufs,
            }
        )

    batch = {
        "schemaVersion": "1.0",
        "candidateType": "audio_review_batch",
        "batchId": batch_id,
        "recipeId": "AR-012-BED-BALANCE",
        "generatorVersion": f"{config.generator_version}-bed-balance-lab-1",
        "candidateCount": len(candidates),
        "durationSec": 11,
        "durationBank": "11s",
        "registrationStatus": "ready_for_review",
        "sourceAudioId": source["audioId"],
        "requirements": {
            "audioOnlyReview": True,
            "singleVariableCalibration": True,
            "onlyBedLevelChanges": True,
            "humanLoopApprovalInherited": True,
        },
        "candidates": candidates,
        "createdAt": created_at,
    }
    (batch_root / "batch-manifest.json").write_text(
        json.dumps(batch, indent=2) + "\n", encoding="utf-8"
    )
    return batch


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a three-step continuous-bed balance calibration")
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
    print(f"Built {result['candidateCount']} bed-balance calibration candidates")


if __name__ == "__main__":
    main()
