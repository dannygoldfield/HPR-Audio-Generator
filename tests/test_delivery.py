from array import array
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import wave

from hpr_audio_generator.delivery import delivery_gain_db, measure_loop


class DeliveryTests(unittest.TestCase):
    def test_delivery_gain_is_a_constant_level_change(self) -> None:
        self.assertEqual(31.0, delivery_gain_db(-53.0, -22.0))

    def test_loop_measurement_accepts_an_ordinary_boundary_step(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "loop.wav"
            samples = array("h", [0, 100, 200, 100] * 1200)
            with wave.open(str(path), "wb") as audio:
                audio.setnchannels(1)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                audio.writeframes(samples.tobytes())
            result = measure_loop(path)
            self.assertTrue(result.click_check_passed)


if __name__ == "__main__":
    unittest.main()
