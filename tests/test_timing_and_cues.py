from __future__ import annotations

import unittest
from pathlib import Path

from pydub import AudioSegment

from workout_audio_coach import audio, cli, config, planner


def _make_config(
    *,
    reps: int = 6,
    sets: int = 2,
    rep_gap: float = 2.0,
    set_gap: float = 30.0,
    countdown: int = 3,
    set_start_gap: float = 1.0,
    timing_mode: config.TimingMode = "gap",
    countdown_gap: float = 1.0,
    countdown_end_gap: float = 0.0,
    rest_warnings: tuple[int, ...] = (),
    announce_halfway: bool = False,
    announce_last_set: bool = False,
) -> config.WorkoutConfig:
    return config.WorkoutConfig(
        reps=reps,
        sets=sets,
        rep_gap=rep_gap,
        set_gap=set_gap,
        output_file=None,
        output_format=None,
        language="en",
        cache_dir=Path("cache"),
        use_cache=True,
        countdown=countdown,
        announce_rest=True,
        set_start_gap=set_start_gap,
        preview=True,
        script_file=None,
        tts_attempts=3,
        tts_initial_backoff=1.0,
        timing_mode=timing_mode,
        countdown_gap=countdown_gap,
        countdown_end_gap=countdown_end_gap,
        rest_warnings=rest_warnings,
        announce_halfway=announce_halfway,
        announce_last_set=announce_last_set,
    )


class TimingAndCuesTests(unittest.TestCase):
    def test_parse_rest_warnings_sorts_descending_and_deduplicates(self) -> None:
        self.assertEqual(config.parse_rest_warnings("3, 10, 1, 2, 10"), (10, 3, 2, 1))
        self.assertEqual(config.parse_rest_warnings(""), ())
        with self.assertRaisesRegex(ValueError, "positive integers"):
            config.parse_rest_warnings("10,0")

    def test_rest_warnings_split_rest_duration_accurately(self) -> None:
        cfg = _make_config(
            reps=2,
            sets=2,
            set_gap=30.0,
            countdown=0,
            rest_warnings=(60, 10, 3, 2, 1),
        )
        plan = planner.build_workout_plan(cfg)
        rest_slice = [step for step in plan if step.section == "Rest after Set 1"]

        self.assertEqual(
            [(step.spoken_text, step.gap_after) for step in rest_slice],
            [
                ("Rest", 20.0),
                ("10 seconds left", 7.0),
                ("3", 1.0),
                ("2", 1.0),
                ("1", 1.0),
            ],
        )
        self.assertEqual(sum(step.gap_after for step in rest_slice), 30.0)

    def test_halfway_and_last_set_cues(self) -> None:
        cfg = _make_config(
            reps=4,
            sets=2,
            countdown=0,
            set_gap=5.0,
            announce_halfway=True,
            announce_last_set=True,
        )
        plan = planner.build_workout_plan(cfg)
        spoken = [step.spoken_text for step in plan]
        self.assertEqual(
            spoken,
            [
                "Set 1",
                "1",
                "2",
                "Halfway",
                "3",
                "4",
                "Rest",
                "Set 2",
                "Last set",
                "1",
                "2",
                "Halfway",
                "3",
                "4",
                "Workout complete",
            ],
        )

    def test_countdown_gap_and_countdown_end_gap(self) -> None:
        cfg = _make_config(
            reps=1,
            sets=1,
            countdown=2,
            countdown_gap=0.5,
            countdown_end_gap=0.75,
        )
        plan = planner.build_workout_plan(cfg)
        self.assertEqual(plan[0].gap_after, 0.5)
        self.assertEqual(plan[1].gap_after, 0.5)
        self.assertEqual(plan[2].gap_after, 0.75)

    def test_cadence_mode_subtracts_spoken_duration(self) -> None:
        cfg = _make_config(
            reps=3,
            sets=1,
            rep_gap=2.0,
            set_gap=0.0,
            countdown=0,
            set_start_gap=0.0,
            timing_mode="cadence",
        )

        def fake_loader(
            phrase: str,
            language: str,
            cache_dir: Path,
            *,
            use_cache: bool = True,
            attempts: int = 3,
            initial_backoff_seconds: float = 1.0,
        ) -> AudioSegment:
            # 400ms per spoken phrase
            return AudioSegment.silent(duration=400)

        combined = audio.build_workout_audio(cfg, segment_loader=fake_loader)
        # Set 1 (400ms) + rep 1 cadence (400 + 1600 = 2000ms)
        # + rep 2 cadence (400 + 1600 = 2000ms) + rep 3 (400ms) + complete (400ms)
        self.assertEqual(len(combined), 5200)

    def test_cadence_mode_clamps_to_zero_when_clip_exceeds_interval(self) -> None:
        cfg = _make_config(
            reps=2,
            sets=1,
            rep_gap=0.5,
            set_gap=0.0,
            countdown=0,
            set_start_gap=0.0,
            timing_mode="cadence",
        )

        def long_loader(
            phrase: str,
            language: str,
            cache_dir: Path,
            *,
            use_cache: bool = True,
            attempts: int = 3,
            initial_backoff_seconds: float = 1.0,
        ) -> AudioSegment:
            return AudioSegment.silent(duration=800)

        combined = audio.build_workout_audio(cfg, segment_loader=long_loader)
        # 4 spoken clips * 800ms, zero extra silence since 800ms > 500ms
        self.assertEqual(len(combined), 3200)

    def test_cli_parses_timing_and_cue_flags(self) -> None:
        parser = cli.create_parser()
        args = parser.parse_args(
            [
                "--reps",
                "8",
                "--sets",
                "3",
                "--rep-gap",
                "2",
                "--set-gap",
                "30",
                "--timing-mode",
                "cadence",
                "--countdown-gap",
                "0.8",
                "--countdown-end-gap",
                "0.5",
                "--rest-warnings",
                "10,3,2,1",
                "--announce-halfway",
                "--announce-last-set",
                "--preview",
            ]
        )
        cfg = cli.build_config(args)
        self.assertEqual(cfg.timing_mode, "cadence")
        self.assertEqual(cfg.countdown_gap, 0.8)
        self.assertEqual(cfg.countdown_end_gap, 0.5)
        self.assertEqual(cfg.rest_warnings, (10, 3, 2, 1))
        self.assertTrue(cfg.announce_halfway)
        self.assertTrue(cfg.announce_last_set)


if __name__ == "__main__":
    unittest.main()
