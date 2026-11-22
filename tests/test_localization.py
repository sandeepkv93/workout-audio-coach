from __future__ import annotations

import unittest
from pathlib import Path

from workout_audio_coach import cli, config, localization, planner


class LocalizationTests(unittest.TestCase):
    def test_get_phrase_pack_resolves_primary_and_regional_subtags(self) -> None:
        es = localization.get_phrase_pack("es-MX")
        self.assertEqual(es.starting_in, "Comenzando en")
        self.assertEqual(es.format_set(2), "Serie 2")
        self.assertEqual(es.rest, "Descansa")
        self.assertEqual(es.workout_complete, "Entrenamiento completo")

        fr = localization.get_phrase_pack("fr_CA")
        self.assertEqual(fr.rest, "Repos")

        fallback = localization.get_phrase_pack("xx-unknown")
        self.assertEqual(fallback, localization.PHRASE_PACKS["en"])

    def test_get_phrase_pack_applies_overrides_and_rejects_unknown_keys(self) -> None:
        pack = localization.get_phrase_pack(
            "en",
            {"rest": "Catch your breath", "set-label": "Block {number}"},
        )
        self.assertEqual(pack.rest, "Catch your breath")
        self.assertEqual(pack.format_set(3), "Block 3")

        with self.assertRaisesRegex(ValueError, "unknown phrase key"):
            localization.get_phrase_pack("en", {"bogus": "nope"})

    def test_parse_phrase_override(self) -> None:
        self.assertEqual(
            localization.parse_phrase_override("workout-complete=All done!"),
            ("workout_complete", "All done!"),
        )
        with self.assertRaisesRegex(ValueError, "expected KEY=VALUE"):
            localization.parse_phrase_override("missing_equals")

    def test_build_workout_plan_uses_localized_phrases_and_overrides(self) -> None:
        cfg = config.WorkoutConfig(
            reps=2,
            sets=2,
            rep_gap=1.0,
            set_gap=10.0,
            output_file=None,
            output_format=None,
            language="es",
            cache_dir=Path("cache"),
            use_cache=True,
            countdown=2,
            announce_rest=True,
            set_start_gap=1.0,
            preview=True,
            script_file=None,
            tts_attempts=3,
            tts_initial_backoff=1.0,
            phrase_overrides=(("workout_complete", "¡Buen trabajo!"),),
        )
        plan = planner.build_workout_plan(cfg)
        spoken = [step.spoken_text for step in plan]
        self.assertEqual(
            spoken,
            [
                "Comenzando en",
                "2",
                "1",
                "Serie 1",
                "1",
                "2",
                "Descansa",
                "Serie 2",
                "1",
                "2",
                "¡Buen trabajo!",
            ],
        )

    def test_cli_parses_phrase_overrides(self) -> None:
        parser = cli.create_parser()
        args = parser.parse_args(
            [
                "--reps",
                "5",
                "--sets",
                "2",
                "--rep-gap",
                "1",
                "--set-gap",
                "15",
                "--language",
                "de",
                "--phrase",
                "rest=Kurze Pause",
                "--preview",
            ]
        )
        cfg = cli.build_config(args)
        self.assertEqual(cfg.language, "de")
        self.assertEqual(cfg.phrase_overrides, (("rest", "Kurze Pause"),))


if __name__ == "__main__":
    unittest.main()
