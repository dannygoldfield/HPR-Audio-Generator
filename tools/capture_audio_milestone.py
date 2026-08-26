from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _latest_review_join() -> str:
    return """
    LEFT JOIN candidate_reviews r ON r.review_id=(
      SELECT MAX(r2.review_id) FROM candidate_reviews r2
      WHERE r2.subject_kind='audio' AND r2.subject_id=a.audio_id
    )
    """


def capture(
    *,
    config_path: Path,
    registry_path: Path,
    output_json: Path,
    output_markdown: Path,
    audio_commit: str,
    umbrella_commit: str,
) -> None:
    root = ET.parse(config_path).getroot()
    assets = [
        {
            "assetId": node.attrib["id"],
            "name": node.attrib.get("name", node.attrib["id"]),
            "role": node.attrib["role"],
            "family": node.attrib["family"],
            "source": node.attrib.get("source", "Unknown"),
            "path": node.attrib["path"],
            "status": node.attrib.get("status", "Active"),
        }
        for node in root.findall("./assets/asset")
    ]
    role_counts = Counter(asset["role"] for asset in assets)
    family_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for asset in assets:
        family_counts[asset["role"]][asset["family"]] += 1

    with sqlite3.connect(registry_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            f"""
            SELECT a.audio_id, a.duration_sec, a.recipe_id, a.seed,
                   a.generator_version, a.media_path, a.manifest_path,
                   r.rating, r.notes
            FROM audio_candidates a
            {_latest_review_join()}
            WHERE a.status='banked'
            ORDER BY a.duration_sec, a.created_at, a.audio_id
            """
        ).fetchall()

    tracks = []
    for row in rows:
        manifest_path = Path(row["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        tracks.append(
            {
                "audioId": row["audio_id"],
                "durationSec": row["duration_sec"],
                "recipeId": row["recipe_id"],
                "seed": row["seed"],
                "generatorVersion": row["generator_version"],
                "rating": row["rating"],
                "notes": row["notes"] or "",
                "ingredients": manifest.get("ingredients", {}),
                "mediaPath": row["media_path"],
                "mediaSha256": manifest.get("output", {}).get("sha256"),
                "manifestPath": row["manifest_path"],
            }
        )

    by_duration = Counter(f"{int(track['durationSec'])}s" for track in tracks)
    screened = next(
        (
            json.loads(Path(row["manifest_path"]).read_text(encoding="utf-8"))
            for row in reversed(rows)
            if row["duration_sec"] == 11
            and "screened" in row["generator_version"]
        ),
        {},
    )
    timestamp = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "schemaVersion": "1.0",
        "milestoneId": "audio-construction-discovery-2026-08-26",
        "capturedAt": timestamp,
        "meaning": (
            "The moment the layered audio construction became legible during "
            "portrait navigation and a bank of reusable loops began to form."
        ),
        "code": {
            "audioGeneratorCommitBeforeAudit": audio_commit,
            "umbrellaCommitAtCapture": umbrella_commit,
        },
        "lockedReferenceConfig": {
            "path": str(config_path),
            "version": root.attrib["version"],
            "sha256": _sha256(config_path),
        },
        "sourceLibrary": {
            "total": len(assets),
            "countsByRole": dict(sorted(role_counts.items())),
            "countsByFamily": {
                role: dict(sorted(counts.items()))
                for role, counts in sorted(family_counts.items())
            },
            "assets": assets,
        },
        "approvedBank": {
            "total": len(tracks),
            "countsByDuration": dict(sorted(by_duration.items())),
            "tracks": tracks,
        },
        "screenedElevenSecondMethod": {
            "mixScreening": screened.get("mixScreening"),
            "loopNativeStructure": screened.get("loopNativeStructure"),
            "delivery": screened.get("delivery"),
            "humanAuthority": (
                "A loop is approved only when continuous listening does not reveal "
                "the transition from end back to beginning."
            ),
        },
    }
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")

    eleven_tracks = [track for track in tracks if track["durationSec"] == 11]
    track_lines = []
    for track in eleven_tracks:
        detail = f"rating {track['rating']}" if track["rating"] else "approved without a numeric rating"
        if track["notes"]:
            detail += f" — {track['notes'].strip()}"
        track_lines.append(f"- `{track['audioId']}` — {detail}")
    mix = snapshot["screenedElevenSecondMethod"]["mixScreening"] or {}
    markdown = f"""# Audio construction discovery — 2026-08-26

This milestone marks the moment the audio system became understandable as a
set of ingredients rather than an opaque generator. While reviewing the large
11-second batch and moving among portraits, Danny could hear how beds,
gestures, and music stems combined—and could already recognize possible
portrait matches. That listening experience is the reason for adding the
Ingredient Audit.

## What is frozen

- Audio Generator code immediately before the audit: `{audio_commit}`
- HPR Umbrella code and review behavior at capture: `{umbrella_commit}`
- Locked generator configuration: `config/generator-0.3.1-reference.xml`
- Locked configuration SHA-256: `{snapshot['lockedReferenceConfig']['sha256']}`
- Source library: {len(assets)} immutable WAV ingredients ({role_counts['Bed']} beds,
  {role_counts['Gesture']} gestures, {role_counts['Music']} music stems)
- Approved bank at capture: {len(tracks)} tracks ({by_duration.get('7s', 0)} at seven seconds,
  {by_duration.get('11s', 0)} at eleven seconds)

## Screened 11-second construction that was working

- Native 11-second composition; never stretched or repeated from seven seconds
- Structurally periodic continuous ambience with events kept clear of the boundary
- Bed target: {mix.get('continuousBedTargetDbfs', 'recorded in manifests')} dBFS
- Gesture target: {mix.get('gestureTargetDbfs', 'recorded in manifests')} dBFS
- Music target: {mix.get('musicTargetDbfs', 'recorded in manifests')} dBFS
- Delivery target: {snapshot['screenedElevenSecondMethod']['delivery'].get('targetLufs', 'recorded in manifests') if snapshot['screenedElevenSecondMethod']['delivery'] else 'recorded in manifests'} LUFS by constant gain only
- No compression or limiting
- Final loop judgment remains human: close the eyes and hear no transition

## Approved 11-second tracks at capture

{chr(10).join(track_lines)}

## What the Ingredient Audit may change

It may record an ingredient as Active, Paused, or Rejected for future candidate
generation, plus a rating and listening note. It may not edit, rename, move, or
delete a WAV file. Prior manifests and approved audio remain intact.

The complete machine-readable snapshot—including the full ingredient roster,
approved-track ingredients, seeds, file hashes, and paths—is in
`data/milestones/2026-08-26-audio-construction-discovery.json`.
"""
    output_markdown.parent.mkdir(parents=True, exist_ok=True)
    output_markdown.write_text(markdown, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture the HPR audio discovery milestone")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    parser.add_argument("--audio-commit", required=True)
    parser.add_argument("--umbrella-commit", required=True)
    args = parser.parse_args()
    capture(
        config_path=args.config.resolve(),
        registry_path=args.registry.resolve(),
        output_json=args.output_json.resolve(),
        output_markdown=args.output_markdown.resolve(),
        audio_commit=args.audio_commit,
        umbrella_commit=args.umbrella_commit,
    )


if __name__ == "__main__":
    main()
