from pathlib import Path
import unittest

from fresh_eleven_batch import _eligible_beds
from hpr_audio_generator.config import load_config


ROOT = Path(__file__).resolve().parents[1]


class FreshElevenBatchTests(unittest.TestCase):
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
