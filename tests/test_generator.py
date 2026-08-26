from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib
import unittest
import wave

from hpr_audio_generator.config import load_config
from array import array

from hpr_audio_generator.generator import _seamless_loop, generate


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_CONFIG = ROOT / "config/generator-0.3.1-reference.xml"


class GeneratorTests(unittest.TestCase):
    REFERENCE_HASHES = {
        2026073001: "b503221ef0cda6eb5ccb10c71fd6be284b87c3d4d2dce534d85a46bba363f7fa",
        2026073002: "9b39f436478d5cbd884fd83ff1d509e1921a76b2bddc46ac97ed4b1d20674ee7",
        2026073003: "6195ef9f436f1e320234ad0ca110624229491848200f24be2fbd6949ef2442a9",
        2026073004: "c2b3a63459fd0cc628d2bdb6e3821bca911baa32bce4c98a159af7c3157f2ef2",
        2026073005: "0bc94577d75af657e86190dd6608d5ce70fa1c77b194a5d97744e7725a86a2f2",
        2026073006: "632fda8ddf01a7bf6328a1faac08ed352b0a15081a41bacecf5c3a78c93740bb",
        2026073007: "a75b6a17b186e212a67837ec205c2d5c0d07d3c659f3cd27dc10660607fa3942",
        2026073008: "8505633a82c98c03f1ed718e791e60489ff1bb3df1fa2a96b0092a77dbbf6704",
        2026073009: "686d66b7ab4f4814f2e061cc3482b445baf4f0c046d70b9af9265e3b6cb99133",
        2026073010: "85cfe117384bf0e03a56d16bb9d777a2a3276e1cb84e6f0798abab5ba65638fb",
    }

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

    def test_native_eleven_second_recipe_preserves_reference_ingredients(self) -> None:
        config = load_config(ROOT / "config/generator.xml")
        with TemporaryDirectory() as directory:
            reference = generate(config, "AR-007", 2026073002, Path(directory) / "reference.wav")
            extended = generate(config, "AR-008", 2026073002, Path(directory) / "extended.wav")
            self.assertEqual(
                (reference.bed_id, reference.gesture_id, reference.music_stem_id),
                (extended.bed_id, extended.gesture_id, extended.music_stem_id),
            )
            with wave.open(str(Path(directory) / "extended.wav"), "rb") as audio:
                self.assertEqual(11 * 48000, audio.getnframes())

    def test_confirmed_reference_batch_is_unchanged(self) -> None:
        config = load_config(REFERENCE_CONFIG)
        with TemporaryDirectory() as directory:
            for seed, expected_hash in self.REFERENCE_HASHES.items():
                output = Path(directory) / f"{seed}.wav"
                generate(config, "AR-007", seed, output)
                self.assertEqual(
                    expected_hash,
                    hashlib.sha256(output.read_bytes()).hexdigest(),
                    f"Reference audio changed for seed {seed}",
                )


if __name__ == "__main__":
    unittest.main()
