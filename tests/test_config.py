from pathlib import Path
import unittest

from hpr_audio_generator.config import load_config


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_audio_only_config_is_valid(self) -> None:
        config = load_config(ROOT / "config/generator.xml")
        self.assertEqual(73, len(config.assets))
        self.assertGreaterEqual(len(config.profiles), 1)
        self.assertGreaterEqual(len(config.recipes), 1)
        self.assertEqual({"Bed", "Gesture"}, {asset.role for asset in config.assets})


if __name__ == "__main__":
    unittest.main()
