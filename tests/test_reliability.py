from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import BinaryIO
from unittest.mock import patch

from pydub import AudioSegment

from workout_audio_coach import audio, cli, config, planner, tts


class _GoodTTS:
    calls = 0

    def __init__(self, *, text: str, lang: str) -> None:
        type(self).calls += 1
        self.payload = f"ok:{lang}:{text}".encode()

    def write_to_fp(self, fp: BinaryIO) -> None:
        fp.write(self.payload)


class _AlwaysFailTTS:
    def __init__(self, *, text: str, lang: str) -> None:
        self.text = text
        self.lang = lang

    def write_to_fp(self, fp: BinaryIO) -> None:
        raise RuntimeError("network down")


class ValidationAndConfigTests(unittest.TestCase):
    def test_float_validators_reject_nan_and_inf(self) -> None:
        parser = cli.create_parser()
        for bad_value in ("nan", "inf", "-inf"):
            with self.subTest(bad_value=bad_value), self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "--reps",
                        "5",
                        "--sets",
                        "2",
                        "--rep-gap",
                        bad_value,
                        "--set-gap",
                        "10",
                        "--preview",
                    ]
                )
            with self.subTest(backoff=bad_value), self.assertRaises(SystemExit):
                parser.parse_args(
                    [
                        "--reps",
                        "5",
                        "--sets",
                        "2",
                        "--rep-gap",
                        "1",
                        "--set-gap",
                        "10",
                        "--tts-backoff",
                        bad_value,
                        "--preview",
                    ]
                )

    def test_resolve_output_format_supports_additional_formats_and_rejects_unknown(self) -> None:
        self.assertEqual(config.resolve_output_format(Path("a.ogg"), None), "ogg")
        self.assertEqual(config.resolve_output_format(Path("a.flac"), None), "flac")
        self.assertEqual(config.resolve_output_format(Path("a.m4a"), None), "m4a")
        self.assertEqual(config.resolve_output_format(Path("a.unknown"), "wav"), "wav")

        with self.assertRaisesRegex(ValueError, "unsupported output file extension"):
            config.resolve_output_format(Path("a.xyz"), None)

        with self.assertRaisesRegex(ValueError, "unsupported output format"):
            config.resolve_output_format(Path("a.mp3"), "aac")

    def test_default_cache_dir_respects_xdg_cache_home(self) -> None:
        with (
            patch.object(sys, "platform", "linux"),
            patch.object(os, "name", "posix"),
            patch.dict(os.environ, {"XDG_CACHE_HOME": "/tmp/custom-xdg-cache"}, clear=False),
        ):
            self.assertEqual(
                config.default_cache_dir(),
                Path("/tmp/custom-xdg-cache/workout-audio-coach"),
            )


class FormattingAndCacheTests(unittest.TestCase):
    def test_format_workout_plan_expands_index_padding_for_100_plus_steps(self) -> None:
        cfg = config.WorkoutConfig(
            reps=10,
            sets=10,
            rep_gap=1.0,
            set_gap=10.0,
            output_file=None,
            output_format=None,
            language="en",
            cache_dir=Path("cache"),
            use_cache=True,
            countdown=3,
            announce_rest=True,
            set_start_gap=1.0,
            preview=True,
            script_file=None,
            tts_attempts=3,
            tts_initial_backoff=1.0,
        )
        plan = planner.build_workout_plan(cfg)
        self.assertGreaterEqual(len(plan), 100)

        formatted = planner.format_workout_plan(cfg, plan)
        self.assertIn("001. Starting in", formatted)
        self.assertIn(f"{len(plan):03d}. Workout complete", formatted)

    def test_corrupt_cache_entry_is_regenerated_atomically(self) -> None:
        _GoodTTS.calls = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_dir = Path(tmpdir)
            cache_file = tts.phrase_cache_path(cache_dir, "Rest", "en")
            cache_file.write_bytes(b"corrupt-bytes")

            def decoder(payload: bytes) -> AudioSegment:
                if payload == b"corrupt-bytes":
                    raise ValueError("bad mp3 header")
                return AudioSegment.silent(duration=250)

            segment = tts.load_or_generate_segment(
                "Rest",
                "en",
                cache_dir,
                use_cache=True,
                tts_factory=_GoodTTS,
                audio_decoder=decoder,
            )

            self.assertEqual(len(segment), 250)
            self.assertEqual(_GoodTTS.calls, 1)
            self.assertEqual(cache_file.read_bytes(), b"ok:en:Rest")
            self.assertEqual(len(list(cache_dir.iterdir())), 1)

    def test_synthesize_phrase_raises_after_exhausting_retries(self) -> None:
        sleep_calls: list[float] = []
        with self.assertRaisesRegex(RuntimeError, "Unable to synthesize speech"):
            tts.synthesize_phrase(
                "Set 1",
                "en",
                attempts=3,
                initial_backoff_seconds=0.5,
                tts_factory=_AlwaysFailTTS,
                sleep_fn=sleep_calls.append,
            )
        self.assertEqual(sleep_calls, [0.5, 1.0])


class AudioAndCLITests(unittest.TestCase):
    def test_concatenate_segments_normalizes_parameters(self) -> None:
        seg_a = AudioSegment.silent(duration=100, frame_rate=24000).set_channels(1)
        seg_b = AudioSegment.silent(duration=200, frame_rate=44100).set_channels(2)
        combined = audio.concatenate_segments([AudioSegment.empty(), seg_a, seg_b])
        self.assertEqual(len(combined), 300)
        self.assertEqual(combined.frame_rate, 24000)
        self.assertEqual(combined.channels, 1)

    def test_concatenate_empty_returns_empty(self) -> None:
        self.assertEqual(len(audio.concatenate_segments([])), 0)

    def test_ensure_ffmpeg_available_raises_helpful_error(self) -> None:
        with (
            patch("workout_audio_coach.tts.shutil.which", return_value=None),
            self.assertRaisesRegex(RuntimeError, "ffmpeg is required"),
        ):
            tts.ensure_ffmpeg_available()

    def test_main_preview_does_not_import_pydub_or_gtts(self) -> None:
        code = (
            "import sys; "
            "from workout_audio_coach.cli import main; "
            "main(['--reps', '2', '--sets', '1', '--rep-gap', '1', "
            "'--set-gap', '5', '--preview']); "
            "assert 'pydub' not in sys.modules, 'pydub should not be imported on preview'; "
            "assert 'gtts' not in sys.modules, 'gtts should not be imported on preview'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Workout Audio Coach plan", result.stdout)

    def test_main_exits_cleanly_on_runtime_error(self) -> None:
        with (
            patch.object(cli, "create_combined_audio", side_effect=RuntimeError("boom")),
            self.assertRaises(SystemExit) as ctx,
        ):
            cli.main(
                [
                    "--reps",
                    "2",
                    "--sets",
                    "1",
                    "--rep-gap",
                    "1",
                    "--set-gap",
                    "5",
                    "--preview",
                ]
            )
        self.assertEqual(ctx.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
