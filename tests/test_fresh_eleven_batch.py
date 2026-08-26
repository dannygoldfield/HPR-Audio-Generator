from pathlib import Path
import unittest

from fresh_eleven_batch import _eligible_beds, _ingredient_combinations
from hpr_audio_generator.config import load_config


ROOT = Path(__file__).resolve().parents[1]


class FreshElevenBatchTests(unittest.TestCase):
    def test_large_batches_use_distinct_deterministic_ingredient_trios(self) -> None:
        config = load_config(ROOT / "config/generator.xml")
        beds = _eligible_beds(
            config,
            allowed_families=("Urban Road", "Interior Mechanical", "Human Distant"),
            excluded_ids=(),
        )[:2]
        gestures = [asset for asset in config.assets if asset.role == "Gesture"][:3]
        music = [asset for asset in config.assets if asset.role == "Music"][:2]
        first = _ingredient_combinations(beds, gestures, music, seed=123)
        second = _ingredient_combinations(beds, gestures, music, seed=123)
        first_ids = [tuple(asset.asset_id for asset in trio) for trio in first]
        second_ids = [tuple(asset.asset_id for asset in trio) for trio in second]
        self.assertEqual(12, len(first_ids))
        self.assertEqual(12, len(set(first_ids)))
        self.assertEqual(first_ids, second_ids)

    def test_screened_beds_respect_family_and_exclusion_rules(self) -> None:
        config = load_config(ROOT / "config/generator.xml")
        beds = _eligible_beds(
            config,
            allowed_families=("Urban Road", "Interior Mechanical"),
            excluded_ids=("SA-B-011", "SA-B-020"),
        )
        self.assertTrue(beds)
        self.assertTrue(
            all(asset.family in {"Urban Road", "Interior Mechanical"} for asset in beds)
        )
        self.assertFalse({"SA-B-011", "SA-B-020"} & {asset.asset_id for asset in beds})


if __name__ == "__main__":
    unittest.main()
