from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from tempfile import NamedTemporaryFile
from typing import Any
import xml.etree.ElementTree as ET

from .config import load_config, load_ingredient_audit


VALID_DECISIONS = {"active", "paused", "rejected"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest_ingredient_ids(manifest: dict[str, Any]) -> set[str]:
    ingredients = manifest.get("ingredients", {})
    result: set[str] = set()
    for role in ("bed", "gesture", "music"):
        value = ingredients.get(role)
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            result.add(value["id"])
    return result


def _candidate_usage(registry_path: Path | None) -> dict[str, dict[str, Any]]:
    usage: dict[str, dict[str, Any]] = {}
    if registry_path is None or not registry_path.is_file():
        return usage
    with sqlite3.connect(registry_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT audio_id, status, media_path, manifest_path
            FROM audio_candidates
            WHERE manifest_path IS NOT NULL
            """
        ).fetchall()
    priority = {"banked": 0, "retired_selected": 1, "ready_for_review": 2}
    for row in rows:
        manifest_path = Path(row["manifest_path"])
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for asset_id in _manifest_ingredient_ids(manifest):
            item = usage.setdefault(
                asset_id,
                {"generated": 0, "banked": 0, "retired": 0, "examples": []},
            )
            item["generated"] += 1
            if row["status"] == "banked":
                item["banked"] += 1
            if row["status"] in {"retired", "retired_selected"}:
                item["retired"] += 1
            media_path = Path(row["media_path"]) if row["media_path"] else None
            if media_path and media_path.is_file():
                item["examples"].append(
                    {
                        "audioId": row["audio_id"],
                        "status": row["status"],
                        "mediaUrl": f"/candidate-media/{row['audio_id']}",
                        "priority": priority.get(row["status"], 9),
                    }
                )
    for item in usage.values():
        item["examples"].sort(
            key=lambda example: (example["priority"], example["audioId"])
        )
        item["examples"] = item["examples"][:3]
        for example in item["examples"]:
            example.pop("priority", None)
    return usage


def ingredient_catalog(
    config_path: Path, *, registry_path: Path | None = None
) -> dict[str, Any]:
    config_path = config_path.resolve()
    config = load_config(config_path)
    document = ET.parse(config_path)
    nodes = document.getroot().findall("./assets/asset")
    by_id = {asset.asset_id: asset for asset in config.assets}
    reviews = (
        load_ingredient_audit(config.ingredient_audit_path)
        if config.ingredient_audit_path
        else {}
    )
    usage = _candidate_usage(registry_path)
    assets = []
    for node in nodes:
        asset_id = node.attrib["id"]
        asset = by_id[asset_id]
        review = reviews.get(asset_id, {})
        assets.append(
            {
                "assetId": asset_id,
                "name": node.attrib.get("name", asset_id),
                "role": asset.role,
                "family": asset.family,
                "source": node.attrib.get("source", "Unknown"),
                "durationSec": float(node.attrib.get("durationSec", "0")),
                "sampleRate": int(node.attrib.get("sampleRate", config.sample_rate)),
                "channels": int(node.attrib.get("channels", config.channels)),
                "mediaUrl": f"/ingredient-media/{asset_id}",
                "decision": review.get("decision", asset.status.lower()),
                "rating": review.get("rating"),
                "notes": review.get("notes", ""),
                "updatedAt": review.get("updatedAt"),
                "usage": usage.get(
                    asset_id,
                    {"generated": 0, "banked": 0, "retired": 0, "examples": []},
                ),
            }
        )
    counts = {
        role: sum(asset["role"] == role for asset in assets)
        for role in ("Bed", "Gesture", "Music")
    }
    decisions = {
        decision: sum(asset["decision"] == decision for asset in assets)
        for decision in sorted(VALID_DECISIONS)
    }
    return {
        "schemaVersion": "1.0",
        "generatorVersion": config.generator_version,
        "counts": counts,
        "decisions": decisions,
        "assets": assets,
    }


def save_ingredient_review(
    config_path: Path,
    *,
    asset_id: str,
    decision: str,
    rating: int | None,
    notes: str,
) -> dict[str, Any]:
    config = load_config(config_path)
    valid_ids = {asset.asset_id for asset in config.assets}
    if asset_id not in valid_ids:
        raise ValueError(f"Unknown ingredient: {asset_id}")
    if decision not in VALID_DECISIONS:
        raise ValueError("decision must be active, paused, or rejected")
    if rating is not None and rating not in range(1, 6):
        raise ValueError("rating must be between 1 and 5")
    if not isinstance(notes, str) or len(notes) > 5000:
        raise ValueError("notes must be text no longer than 5000 characters")
    audit_path = config.ingredient_audit_path
    if audit_path is None:
        raise ValueError("Configuration has no ingredientAuditPath")
    if audit_path.is_file():
        document = json.loads(audit_path.read_text(encoding="utf-8"))
    else:
        document = {"schemaVersion": "1.0", "updatedAt": None, "assets": {}}
    updated_at = _now()
    review = {
        "decision": decision,
        "rating": rating,
        "notes": notes,
        "updatedAt": updated_at,
    }
    document["assets"][asset_id] = review
    document["updatedAt"] = updated_at
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=audit_path.parent, delete=False
    ) as temporary:
        json.dump(document, temporary, indent=2)
        temporary.write("\n")
        temporary_path = Path(temporary.name)
    temporary_path.replace(audit_path)
    return review


def ingredient_media_path(config_path: Path, asset_id: str) -> Path:
    config = load_config(config_path)
    for asset in config.assets:
        if asset.asset_id == asset_id:
            return asset.path
    raise ValueError(f"Unknown ingredient: {asset_id}")


def candidate_media_path(registry_path: Path, audio_id: str) -> Path:
    if not registry_path.is_file():
        raise ValueError("Audio registry is unavailable")
    with sqlite3.connect(registry_path) as connection:
        row = connection.execute(
            "SELECT media_path FROM audio_candidates WHERE audio_id=?", (audio_id,)
        ).fetchone()
    if not row or not row[0]:
        raise ValueError(f"Unknown audio candidate: {audio_id}")
    return Path(row[0])
