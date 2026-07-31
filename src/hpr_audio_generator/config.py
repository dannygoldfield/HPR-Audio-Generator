from __future__ import annotations

from dataclasses import dataclass
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

    assets = tuple(
        Asset(
            asset_id=node.attrib["id"],
            role=node.attrib["role"],
            family=node.attrib["family"],
            path=root / node.attrib["path"],
            status=node.attrib.get("status", "Active"),
        )
        for node in config.findall("./assets/asset")
    )
    profiles = {
        node.attrib["id"]: Profile(
            profile_id=node.attrib["id"],
            bed_gain_db=float(node.attrib["bedGainDb"]),
            gesture_gain_db=float(node.attrib["gestureGainDb"]),
            music_gain_db=float(node.attrib.get("musicGainDb", "-24")),
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
        assets=assets,
        profiles=profiles,
        recipes=recipes,
    )
    validate_config(result)
    return result


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
