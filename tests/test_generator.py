from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave

from hpr_audio_generator.config import load_config
from hpr_audio_generator.generator import generate


ROOT = Path(__file__).resolve().parents[1]


class GeneratorTests(unittest.TestCase):
    def test_seed_is_reproducible(self) -> None:
        config = load_config(ROOT / "config/generator.xml")
        with TemporaryDirectory() as directory:
            first = Path(directory) / "first.wav"
            second = Path(directory) / "second.wav"
            a = generate(config, "AR-001", 12345, first)
            b = generate(config, "AR-001", 12345, second)
            self.assertEqual((a.bed_id, a.gesture_id, a.gesture_start_sec), (b.bed_id, b.gesture_id, b.gesture_start_sec))
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with wave.open(str(first), "rb") as audio:
                self.assertEqual(7 * 48000, audio.getnframes())
                self.assertEqual(2, audio.getnchannels())
                self.assertEqual(48000, audio.getframerate())


if __name__ == "__main__":
    unittest.main()

