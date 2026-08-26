from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import wave

from hpr_audio_generator.config import load_config
from hpr_audio_generator.ingredient_audit import (
    ingredient_catalog,
    save_ingredient_review,
)


class IngredientAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "config").mkdir()
        (self.root / "data").mkdir()
        (self.root / "audio/source/beds").mkdir(parents=True)
        self.wav_path = self.root / "audio/source/beds/test.wav"
        with wave.open(str(self.wav_path), "wb") as output:
            output.setnchannels(2)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(b"\0" * 48_000 * 2 * 2)
        self.config_path = self.root / "config/generator.xml"
        self.config_path.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<audioGenerator name="Test" version="1.0" ingredientAuditPath="data/ingredient-audit.json">
  <purpose>Test</purpose>
  <libraryTarget approved="1" provisional="1"/>
  <outputFormat sampleRate="48000" channels="2" sampleWidthBits="16" format="WAV"/>
  <profiles></profiles>
  <recipes></recipes>
  <assets>
    <asset id="TEST-BED" name="Test Bed" role="Bed" family="Test Family"
      path="audio/source/beds/test.wav" source="Test Source" durationSec="1"
      sampleRate="48000" channels="2" status="Active"/>
  </assets>
</audioGenerator>
""",
            encoding="utf-8",
        )
        (self.root / "data/ingredient-audit.json").write_text(
            '{"schemaVersion":"1.0","updatedAt":null,"assets":{}}\n',
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_review_is_non_destructive_and_controls_future_eligibility(self) -> None:
        original_hash = hashlib.sha256(self.wav_path.read_bytes()).hexdigest()
        review = save_ingredient_review(
            self.config_path,
            asset_id="TEST-BED",
            decision="paused",
            rating=4,
            notes="Keep available, but do not use in the next batch.",
        )

        self.assertEqual("paused", review["decision"])
        self.assertEqual(original_hash, hashlib.sha256(self.wav_path.read_bytes()).hexdigest())
        config = load_config(self.config_path)
        self.assertEqual("Paused", config.assets[0].status)

    def test_catalog_combines_metadata_review_and_candidate_usage(self) -> None:
        save_ingredient_review(
            self.config_path,
            asset_id="TEST-BED",
            decision="active",
            rating=5,
            notes="A useful room tone.",
        )
        candidate = self.root / "candidate.wav"
        candidate.write_bytes(self.wav_path.read_bytes())
        manifest = self.root / "candidate.json"
        manifest.write_text(
            json.dumps({"ingredients": {"bed": {"id": "TEST-BED"}}}),
            encoding="utf-8",
        )
        registry = self.root / "registry.sqlite3"
        with sqlite3.connect(registry) as connection:
            connection.execute(
                """CREATE TABLE audio_candidates (
                    audio_id TEXT, status TEXT, media_path TEXT, manifest_path TEXT
                )"""
            )
            connection.execute(
                "INSERT INTO audio_candidates VALUES (?, ?, ?, ?)",
                ("AUD-TEST", "banked", str(candidate), str(manifest)),
            )

        catalog = ingredient_catalog(self.config_path, registry_path=registry)

        self.assertEqual({"Bed": 1, "Gesture": 0, "Music": 0}, catalog["counts"])
        asset = catalog["assets"][0]
        self.assertEqual(5, asset["rating"])
        self.assertEqual("A useful room tone.", asset["notes"])
        self.assertEqual(1, asset["usage"]["generated"])
        self.assertEqual(1, asset["usage"]["banked"])
        self.assertEqual("AUD-TEST", asset["usage"]["examples"][0]["audioId"])
        self.assertNotIn("priority", asset["usage"]["examples"][0])

    def test_invalid_decision_is_rejected_without_writing(self) -> None:
        audit_path = self.root / "data/ingredient-audit.json"
        before = audit_path.read_text(encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "decision must"):
            save_ingredient_review(
                self.config_path,
                asset_id="TEST-BED",
                decision="delete",
                rating=None,
                notes="",
            )
        self.assertEqual(before, audit_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
