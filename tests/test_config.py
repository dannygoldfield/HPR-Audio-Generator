from pathlib import Path
import unittest

from hpr_audio_generator.config import _effective_asset_status, load_config


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_audio_only_config_is_valid(self) -> None:
        config = load_config(ROOT / "config/generator.xml")
        self.assertEqual(90, len(config.assets))
        self.assertGreaterEqual(len(config.profiles), 1)
        self.assertGreaterEqual(len(config.recipes), 1)
        self.assertEqual({"Bed", "Gesture", "Music"}, {asset.role for asset in config.assets})
        self.assertEqual(11, config.recipes["AR-008"].duration_sec)
        self.assertEqual("AP-004", config.recipes["AR-008"].profile_id)
        self.assertEqual(ROOT / "data/ingredient-audit.json", config.ingredient_audit_path)

    def test_ingredient_audit_decisions_override_generation_eligibility(self) -> None:
        self.assertEqual("Active", _effective_asset_status("Active", "active"))
        self.assertEqual("Paused", _effective_asset_status("Active", "paused"))
        self.assertEqual("Rejected", _effective_asset_status("Active", "rejected"))
        self.assertEqual("Active", _effective_asset_status("Active", None))


if __name__ == "__main__":
    unittest.main()
