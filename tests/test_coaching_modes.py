from __future__ import annotations

import io
import unittest
from pathlib import Path

from workout_audio_coach import cli, config, live, pcm, planner, routines

REPO_ROOT = Path(__file__).resolve().parent.parent


class TempoCoachingTests(unittest.TestCase):
    def test_parse_tempo_valid_and_invalid(self) -> None:
        spec3 = config.parse_tempo("3-1-1")
        self.assertEqual(spec3, config.TempoSpec(eccentric=3, pause=1, concentric=1, top_pause=0))
        self.assertEqual(spec3.label(), "3-1-1")

        spec4 = config.parse_tempo("4-0-2-1")
        self.assertEqual(spec4.top_pause, 1)
        self.assertEqual(spec4.label(), "4-0-2-1")

        for bad in ("3-1", "0-1-1", "3-1-0", "3--1-1", "a-b-c"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                config.parse_tempo(bad)

    def test_tempo_plan_generates_localized_phase_cues(self) -> None:
        parser = cli.create_parser()
        args = parser.parse_args(
            [
                "--reps",
                "2",
                "--sets",
                "1",
                "--rep-gap",
                "1",
                "--set-gap",
                "10",
                "--countdown",
                "0",
                "--tempo",
                "3-1-2",
                "--language",
                "es",
                "--preview",
            ]
        )
        cfg = cli.build_config(args)
        plan = planner.build_workout_plan(cfg)
        spoken = [step.spoken_text for step in plan]
        self.assertEqual(
            spoken,
            [
                "Serie 1",
                "1",
                "Baja",
                "2",
                "3",
                "Mantén",
                "Sube",
                "2",
                "2",
                "Baja",
                "2",
                "3",
                "Mantén",
                "Sube",
                "2",
                "Entrenamiento completo",
            ],
        )
        preview = planner.format_workout_plan(cfg, plan)
        self.assertIn("Tempo: 3-1-2", preview)


class CircuitRoutineTests(unittest.TestCase):
    def test_superset_circuit_example_loads_and_plans(self) -> None:
        routine = routines.load_routine_file(REPO_ROOT / "examples" / "superset_circuit.toml")
        self.assertEqual(len(routine.circuits), 1)
        self.assertEqual(routine.total_exercise_count(), 2)
        self.assertEqual(routine.total_set_count(), 6)

        parser = cli.create_parser()
        args = parser.parse_args(
            [
                "--routine",
                str(REPO_ROOT / "examples" / "superset_circuit.toml"),
                "--preview",
            ]
        )
        cfg = cli.build_config(args)
        plan = planner.build_workout_plan(cfg)
        spoken = [step.spoken_text for step in plan]
        self.assertIn("Push & Core Superset", spoken)
        self.assertEqual(spoken.count("Tempo Push-ups"), 3)
        self.assertEqual(spoken.count("Hollow Body Hold"), 3)
        self.assertIn("Down", spoken)
        self.assertIn("Hold", spoken)
        self.assertIn("Up", spoken)
        self.assertIn("Last set", spoken)

    def test_hiit_preset_uses_circuit(self) -> None:
        hiit = routines.get_preset_routine("hiit")
        self.assertEqual(len(hiit.circuits), 1)
        self.assertEqual(hiit.circuits[0].rounds, 3)


class LiveTerminalCoachTests(unittest.TestCase):
    def _sample_config(self) -> config.WorkoutConfig:
        return config.WorkoutConfig(
            reps=2,
            sets=1,
            rep_gap=0.2,
            set_gap=0.0,
            output_file=None,
            output_format=None,
            language="en",
            cache_dir=Path("cache"),
            use_cache=False,
            countdown=0,
            announce_rest=True,
            set_start_gap=0.2,
            preview=False,
            script_file=None,
            tts_attempts=1,
            tts_initial_backoff=0.1,
            tts_backend="tone",
            live=True,
            live_silent=True,
        )

    def test_live_coach_runs_to_completion_with_audio_player(self) -> None:
        cfg = self._sample_config()
        plan = planner.build_workout_plan(cfg)
        out = io.StringIO()
        played: list[pcm.PCMAudio] = []
        now = [0.0]

        def fake_sleep(dt: float) -> None:
            now[0] += dt

        result = live.run_live_coach(
            cfg,
            plan,
            silent=False,
            output_stream=out,
            sleep_fn=fake_sleep,
            clock_fn=lambda: now[0],
            key_reader=lambda: None,
            audio_player=played.append,
            tick_seconds=0.1,
        )
        self.assertTrue(result.completed)
        self.assertEqual(result.steps_completed, len(plan))
        self.assertEqual(result.steps_skipped, 0)
        self.assertEqual(len(played), len(plan))
        self.assertIn("Workout finished", out.getvalue())

    def test_live_coach_handles_pause_skip_and_quit(self) -> None:
        cfg = self._sample_config()
        plan = planner.build_workout_plan(cfg)
        out = io.StringIO()
        # Pause -> Resume -> Skip first step -> Quit on next wait
        keys = iter([" ", " ", "n", "q"])
        now = [0.0]

        def fake_sleep(dt: float) -> None:
            now[0] += dt

        result = live.run_live_coach(
            cfg,
            plan,
            silent=True,
            output_stream=out,
            sleep_fn=fake_sleep,
            clock_fn=lambda: now[0],
            key_reader=lambda: next(keys, None),
            tick_seconds=0.05,
        )
        self.assertFalse(result.completed)
        self.assertEqual(result.steps_skipped, 1)
        rendered = out.getvalue()
        self.assertIn("[PAUSED]", rendered)
        self.assertIn("[RESUMED]", rendered)
        self.assertIn("Workout stopped", rendered)


if __name__ == "__main__":
    unittest.main()
