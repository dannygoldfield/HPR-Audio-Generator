from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave

from hpr_audio_generator.config import load_config
from array import array

from hpr_audio_generator.generator import _seamless_loop, generate


ROOT = Path(__file__).resolve().parents[1]


class GeneratorTests(unittest.TestCase):
    def test_seamless_loop_overlaps_tail_into_head(self) -> None:
        source = array("h", [10, 20, 30, 40, 50, 60, 70])
        loop = _seamless_loop(source, target_samples=5, fade_frames=2, channels=1)
        self.assertEqual(array("h", [60, 20, 30, 40, 50]), loop)

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

    def test_music_recipe_is_reproducible_and_preserves_baseline_choices(self) -> None:
        config = load_config(ROOT / "config/generator.xml")
        with TemporaryDirectory() as directory:
            baseline = generate(config, "AR-001", 2026073001, Path(directory) / "baseline.wav")
            first = generate(config, "AR-006", 2026073001, Path(directory) / "music-first.wav")
            second = generate(config, "AR-006", 2026073001, Path(directory) / "music-second.wav")
            self.assertEqual((baseline.bed_id, baseline.gesture_id, baseline.gesture_start_sec), (first.bed_id, first.gesture_id, first.gesture_start_sec))
            self.assertIsNotNone(first.music_stem_id)
            self.assertEqual((first.bed_id, first.gesture_id, first.gesture_start_sec, first.music_stem_id, first.music_start_sec), (second.bed_id, second.gesture_id, second.gesture_start_sec, second.music_stem_id, second.music_start_sec))
            self.assertEqual((Path(directory) / "music-first.wav").read_bytes(), (Path(directory) / "music-second.wav").read_bytes())

    def test_seamless_recipe_preserves_music_recipe_choices(self) -> None:
        config = load_config(ROOT / "config/generator.xml")
        with TemporaryDirectory() as directory:
            original = generate(config, "AR-006", 2026073001, Path(directory) / "original.wav")
            seamless = generate(config, "AR-007", 2026073001, Path(directory) / "seamless.wav")
            self.assertEqual(
                (original.bed_id, original.gesture_id, original.gesture_start_sec, original.music_stem_id, original.music_start_sec),
                (seamless.bed_id, seamless.gesture_id, seamless.gesture_start_sec, seamless.music_stem_id, seamless.music_start_sec),
            )
            self.assertNotEqual((Path(directory) / "original.wav").read_bytes(), (Path(directory) / "seamless.wav").read_bytes())


if __name__ == "__main__":
    unittest.main()
