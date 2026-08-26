from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import xml.etree.ElementTree as ET


@dataclass(frozen=True)
class Asset:
    asset_id: str
    role: str
    family: str
    path: Path
    status: str


@dataclass(frozen=True)
class Profile:
    profile_id: str
    bed_gain_db: float
    gesture_gain_db: float
    music_gain_db: float
    loop_crossfade_sec: float
    min_gestures: int
    max_gestures: int
    avoid_first_sec: float
    avoid_last_sec: float


@dataclass(frozen=True)
class Recipe:
    recipe_id: str
    profile_id: str
    duration_sec: int
    bed_family: str | None
    gesture_family: str | None
    use_music_stem: bool


@dataclass(frozen=True)
class Config:
    root: Path
    generator_version: str
    sample_rate: int
    channels: int
    sample_width_bits: int
    ingredient_audit_path: Path | None
    assets: tuple[Asset, ...]
    profiles: dict[str, Profile]
    recipes: dict[str, Recipe]


def load_config(path: Path) -> Config:
    path = path.resolve()
    root = path.parent.parent
    document = ET.parse(path)
    config = document.getroot()
    fmt = config.find("outputFormat")
    if fmt is None:
        raise ValueError("Missing outputFormat")

    audit_reference = config.attrib.get("ingredientAuditPath")
    audit_path = (root / audit_reference).resolve() if audit_reference else None
    audit_decisions = load_ingredient_audit(audit_path) if audit_path else {}

    assets = tuple(
        Asset(
            asset_id=node.attrib["id"],
            role=node.attrib["role"],
            family=node.attrib["family"],
            path=root / node.attrib["path"],
            status=_effective_asset_status(
                node.attrib.get("status", "Active"),
                audit_decisions.get(node.attrib["id"], {}).get("decision"),
            ),
        )
        for node in config.findall("./assets/asset")
    )
    profiles = {
        node.attrib["id"]: Profile(
            profile_id=node.attrib["id"],
            bed_gain_db=float(node.attrib["bedGainDb"]),
            gesture_gain_db=float(node.attrib["gestureGainDb"]),
            music_gain_db=float(node.attrib.get("musicGainDb", "-24")),
            loop_crossfade_sec=float(node.attrib.get("loopCrossfadeSec", "0")),
            min_gestures=int(node.attrib["minGestures"]),
            max_gestures=int(node.attrib["maxGestures"]),
            avoid_first_sec=float(node.attrib["avoidFirstSec"]),
            avoid_last_sec=float(node.attrib["avoidLastSec"]),
        )
        for node in config.findall("./profiles/profile")
    }
    recipes = {
        node.attrib["id"]: Recipe(
            recipe_id=node.attrib["id"],
            profile_id=node.attrib["profileId"],
            duration_sec=int(node.attrib["durationSec"]),
            bed_family=node.attrib.get("bedFamily") or None,
            gesture_family=node.attrib.get("gestureFamily") or None,
            use_music_stem=node.attrib.get("useMusicStem", "No") == "Yes",
        )
        for node in config.findall("./recipes/recipe")
    }
    result = Config(
        root=root,
        generator_version=config.attrib["version"],
        sample_rate=int(fmt.attrib["sampleRate"]),
        channels=int(fmt.attrib["channels"]),
        sample_width_bits=int(fmt.attrib["sampleWidthBits"]),
        ingredient_audit_path=audit_path,
        assets=assets,
        profiles=profiles,
        recipes=recipes,
    )
    validate_config(result)
    return result


def load_ingredient_audit(path: Path) -> dict[str, dict[str, object]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != "1.0" or not isinstance(payload.get("assets"), dict):
        raise ValueError(f"Invalid ingredient audit: {path}")
    decisions = payload["assets"]
    for asset_id, review in decisions.items():
        if not isinstance(asset_id, str) or not isinstance(review, dict):
            raise ValueError(f"Invalid ingredient audit entry: {asset_id}")
        if review.get("decision") not in {"active", "paused", "rejected"}:
            raise ValueError(f"Invalid ingredient decision for {asset_id}")
    return decisions


def _effective_asset_status(config_status: str, audit_decision: object) -> str:
    if audit_decision == "active":
        return "Active"
    if audit_decision == "paused":
        return "Paused"
    if audit_decision == "rejected":
        return "Rejected"
    return config_status


def validate_config(config: Config) -> None:
    ids = [asset.asset_id for asset in config.assets]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate asset IDs")
    for asset in config.assets:
        if not asset.path.is_file():
            raise ValueError(f"Missing asset: {asset.asset_id} at {asset.path}")
    for recipe in config.recipes.values():
        if recipe.profile_id not in config.profiles:
            raise ValueError(f"{recipe.recipe_id} references unknown profile {recipe.profile_id}")
        if recipe.duration_sec not in {7, 9, 11}:
            raise ValueError(f"{recipe.recipe_id} has unsupported duration")
        if recipe.use_music_stem and not any(
            asset.role == "Music" and asset.status == "Active" for asset in config.assets
        ):
            raise ValueError(f"{recipe.recipe_id} requires an active music stem")
