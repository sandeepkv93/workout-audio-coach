from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from workout_audio_coach import cli, planner, routines

REPO_ROOT = Path(__file__).resolve().parent.parent


class RoutineLoaderTests(unittest.TestCase):
    def test_load_example_toml_routine(self) -> None:
        routine = routines.load_routine_file(REPO_ROOT / "examples" / "full_body.toml")
        self.assertEqual(routine.name, "Full Body Strength & Core")
        self.assertEqual(len(routine.exercises), 3)
        self.assertEqual(routine.exercises[0].rep_counts(), (12, 10, 8))
        self.assertEqual(routine.exercises[1].rep_counts(), (15, 15, 15))
        self.assertEqual(routine.exercises[2].duration, 45.0)
        self.assertEqual(routine.rest_warnings, (10, 3, 2, 1))

    def test_load_example_json_routine(self) -> None:
        routine = routines.load_routine_file(REPO_ROOT / "examples" / "tabata.json")
        self.assertEqual(routine.name, "Tabata 4-Minute Sprint")
        self.assertEqual(routine.timing_mode, "cadence")
        self.assertEqual(routine.exercises[0].sets, 8)
        self.assertEqual(routine.exercises[0].duration, 20.0)

    def test_routine_validation_errors(self) -> None:
        with self.assertRaisesRegex(ValueError, "non-empty 'exercises'"):
            routines.parse_routine_dict({"name": "Empty", "exercises": []})

        with self.assertRaisesRegex(ValueError, "either 'reps' or 'duration'"):
            routines.parse_routine_dict({"exercises": [{"name": "Mystery"}]})

        with self.assertRaisesRegex(ValueError, "cannot specify both"):
            routines.parse_routine_dict(
                {"exercises": [{"name": "Both", "reps": 10, "duration": 5}]}
            )

        with self.assertRaisesRegex(ValueError, "does not match length of reps"):
            routines.parse_routine_dict(
                {"exercises": [{"name": "Mismatch", "sets": 2, "reps": [10, 8, 6]}]}
            )

        with tempfile.TemporaryDirectory() as tmpdir:
            bad_ext = Path(tmpdir) / "workout.yaml"
            bad_ext.write_text("name: test\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported routine file extension"):
                routines.load_routine_file(bad_ext)


class RoutinePlanningAndCLITests(unittest.TestCase):
    def test_multi_exercise_pyramid_and_timed_plan(self) -> None:
        routine = routines.load_routine_file(REPO_ROOT / "examples" / "full_body.toml")
        parser = cli.create_parser()
        args = parser.parse_args(
            [
                "--routine",
                str(REPO_ROOT / "examples" / "full_body.toml"),
                "--preview",
            ]
        )
        cfg = cli.build_config(args)
        self.assertEqual(cfg.routine, routine)

        plan = planner.build_workout_plan(cfg)
        spoken = [step.spoken_text for step in plan]
        self.assertIn("Push-ups", spoken)
        self.assertIn("Bodyweight Squats", spoken)
        self.assertIn("Plank", spoken)
        self.assertIn("Go", spoken)
        self.assertIn("Halfway", spoken)
        self.assertIn("Last set", spoken)
        self.assertEqual(spoken[-1], "Workout complete")

        formatted = planner.format_workout_plan(cfg, plan)
        self.assertIn("Routine: Full Body Strength & Core (3 exercises)", formatted)

    def test_builtin_presets_and_list_presets_cli(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            cli.main(["--list-presets"])
        output = buf.getvalue()
        for preset in routines.PRESET_NAMES:
            self.assertIn(preset, output)

        parser = cli.create_parser()
        args = parser.parse_args(["--preset", "tabata", "--preview"])
        cfg = cli.build_config(args)
        self.assertEqual(cfg.timing_mode, "cadence")
        self.assertEqual(cfg.rest_warnings, (3, 2, 1))
        plan = planner.build_workout_plan(cfg)
        self.assertIn("Round 8", [step.spoken_text for step in plan])

    def test_cli_timed_duration_mode(self) -> None:
        parser = cli.create_parser()
        args = parser.parse_args(
            [
                "--duration",
                "30",
                "--sets",
                "3",
                "--set-gap",
                "15",
                "--announce-halfway",
                "--preview",
            ]
        )
        cfg = cli.build_config(args)
        self.assertEqual(cfg.duration, 30.0)
        plan = planner.build_workout_plan(cfg)
        spoken = [step.spoken_text for step in plan]
        self.assertEqual(spoken.count("Go"), 3)
        self.assertEqual(spoken.count("Halfway"), 3)
        formatted = planner.format_workout_plan(cfg, plan)
        self.assertIn("Intervals: 3 x 30s", formatted)

    def test_cli_rejects_conflicting_routine_and_preset(self) -> None:
        parser = cli.create_parser()
        args = parser.parse_args(
            [
                "--routine",
                str(REPO_ROOT / "examples" / "tabata.json"),
                "--preset",
                "tabata",
                "--preview",
            ]
        )
        with self.assertRaisesRegex(ValueError, "cannot specify both --routine and --preset"):
            cli.build_config(args)


if __name__ == "__main__":
    unittest.main()
