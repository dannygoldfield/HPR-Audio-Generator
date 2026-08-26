from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from hpr_audio_generator.config import load_config
from hpr_audio_generator.delivery import measure_loudness, measure_loop, sha256, wav_duration
from hpr_audio_generator.generator import generate


SEED_RE = re.compile(r"seed-(\d+)\.wav$")


def bank_reference_batch(
    *,
    config_path: Path,
    batch_root: Path,
    batch_id: str,
) -> dict[str, object]:
    config = load_config(config_path)
    files = sorted(batch_root.glob("*.wav"))
    if len(files) != 10:
        raise ValueError(f"Expected ten approved reference files, found {len(files)}")
    created_at = datetime.now(timezone.utc).isoformat()
    candidates = []
    with TemporaryDirectory() as directory:
        scratch = Path(directory)
        for position, media_path in enumerate(files, start=1):
            match = SEED_RE.search(media_path.name)
            if not match:
                raise ValueError(f"Could not read seed from {media_path.name}")
            seed = int(match.group(1))
            regenerated = scratch / f"{seed}.wav"
            track = generate(config, "AR-007", seed, regenerated)
            media_hash = sha256(media_path)
            if sha256(regenerated) != media_hash:
                raise ValueError(f"Reference fingerprint changed for seed {seed}")
            audio_id = f"AUD-7S-{media_hash[:10].upper()}"
            manifest_path = batch_root / f"{audio_id}.json"
            loudness = measure_loudness(media_path)
            loop = measure_loop(media_path)
            manifest = {
                "schemaVersion": "1.0",
                "candidateType": "audio",
                "audioId": audio_id,
                "batchId": batch_id,
                "reviewPosition": position,
                "recipeId": "AR-007",
                "generatorVersion": "0.3.0-reference",
                "durationSec": wav_duration(media_path),
                "durationBank": "7s",
                "seed": seed,
                "ingredients": {
                    "bed": {"id": track.bed_id, "startSec": 0.0},
                    "gesture": {
                        "id": track.gesture_id,
                        "startSec": round(track.gesture_start_sec, 6),
                    },
                    "music": {
                        "id": track.music_stem_id,
                        "startSec": round(track.music_start_sec or 0.0, 6),
                    },
                },
                "approval": {
                    "status": "banked",
                    "humanApproved": True,
                    "approvedAt": created_at,
                    "note": "Exact ten-track seven-second reference batch approved for its own duration bank.",
                },
                "delivery": {
                    "method": "unaltered approved reference master",
                    "deliveredIntegratedLufs": loudness.integrated_lufs,
                    "deliveredTruePeakDbfs": loudness.true_peak_dbfs,
                },
                "loopValidation": {
                    "humanLoopApproved": True,
                    "humanApprovalOverridesClickOnlyMetrics": True,
                    "seamStep": loop.seam_step,
                    "ordinaryStepP999": loop.ordinary_step_p999,
                    "edgeDeltaDb": loop.edge_delta_db,
                },
                "format": {
                    "container": "WAV",
                    "sampleRate": config.sample_rate,
                    "channels": config.channels,
                    "sampleWidthBits": config.sample_width_bits,
                    "nativeDuration": True,
                },
                "output": {
                    "path": str(media_path.resolve()),
                    "sha256": media_hash,
                    "originalFilename": media_path.name,
                },
                "createdAt": created_at,
            }
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            candidates.append(
                {
                    "audioId": audio_id,
                    "seed": seed,
                    "audio": str(media_path.resolve()),
                    "manifest": str(manifest_path.resolve()),
                    "loudnessLufs": loudness.integrated_lufs,
                    "loopApproval": "human approved",
                }
            )
    batch = {
        "schemaVersion": "1.0",
        "candidateType": "audio_review_batch",
        "batchId": batch_id,
        "recipeId": "AR-007",
        "generatorVersion": "0.3.0-reference",
        "candidateCount": len(candidates),
        "durationSec": 7,
        "durationBank": "7s",
        "registrationStatus": "banked",
        "requirements": {
            "audioOnlyReview": True,
            "humanApproved": True,
            "exactReferenceFiles": True,
            "keepSeparateByDuration": True,
        },
        "candidates": candidates,
        "createdAt": created_at,
    }
    (batch_root / "batch-manifest.json").write_text(
        json.dumps(batch, indent=2) + "\n", encoding="utf-8"
    )
    return batch


def main() -> None:
    parser = argparse.ArgumentParser(description="Bank the confirmed seven-second reference batch")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--batch-root", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    args = parser.parse_args()
    result = bank_reference_batch(
        config_path=args.config,
        batch_root=args.batch_root,
        batch_id=args.batch_id,
    )
    print(f"Banked {result['candidateCount']} exact seven-second reference tracks")


if __name__ == "__main__":
    main()
