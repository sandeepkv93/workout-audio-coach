from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from workout_audio_coach import audio, cli, config, planner, timeline


class TimelineAndMetadataTests(unittest.TestCase):
    def test_format_duration_minutes_and_hours(self) -> None:
        self.assertEqual(timeline.format_duration(0), "0:00")
        self.assertEqual(timeline.format_duration(65), "1:05")
        self.assertEqual(timeline.format_duration(3661), "1:01:01")

    def test_estimated_timeline_and_cue_exports(self) -> None:
        cfg = config.WorkoutConfig(
            reps=2,
            sets=2,
            rep_gap=1.0,
            set_gap=10.0,
            output_file=None,
            output_format=None,
            language="en",
            cache_dir=Path("cache"),
            use_cache=True,
            countdown=2,
            announce_rest=True,
            set_start_gap=1.0,
            preview=False,
            script_file=None,
            tts_attempts=3,
            tts_initial_backoff=1.0,
            title="Morning Warmup",
        )
        plan = planner.build_workout_plan(cfg)
        preview = planner.format_workout_plan(cfg, plan)
        self.assertIn("Title: Morning Warmup", preview)
        self.assertIn("Estimated duration:", preview)

        est = timeline.build_estimated_timeline(plan)
        self.assertTrue(est.is_estimated)
        self.assertGreater(est.total_seconds, 10.0)
        self.assertGreaterEqual(len(est.chapters), 4)

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            vtt_path = timeline.export_timeline(est, root / "cues.vtt")
            srt_path = timeline.export_timeline(est, root / "cues.srt")
            lrc_path = timeline.export_timeline(est, root / "cues.lrc")
            json_path = timeline.export_timeline(est, root / "cues.json")

            self.assertTrue(vtt_path.read_text(encoding="utf-8").startswith("WEBVTT"))
            self.assertIn("-->", srt_path.read_text(encoding="utf-8"))
            self.assertIn("[00:00.00]Starting in", lrc_path.read_text(encoding="utf-8"))

            parsed = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertTrue(parsed["is_estimated"])
            self.assertEqual(parsed["total_seconds"], est.total_seconds)
            self.assertEqual(len(parsed["chapters"]), len(est.chapters))

            with self.assertRaisesRegex(ValueError, "unsupported timestamps file extension"):
                timeline.export_timeline(est, root / "cues.txt")

    def test_exact_timeline_exported_during_offline_wav_build(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_wav = root / "workout.wav"
            out_json = root / "workout.json"
            cli.main(
                [
                    "--reps",
                    "2",
                    "--sets",
                    "2",
                    "--rep-gap",
                    "0.2",
                    "--set-gap",
                    "0.5",
                    "--countdown",
                    "0",
                    "--tts-backend",
                    "tone",
                    "--no-cache",
                    "--output-file",
                    str(out_wav),
                    "--timestamps-file",
                    str(out_json),
                ]
            )
            self.assertTrue(out_wav.exists())
            self.assertTrue(out_json.exists())
            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertFalse(data["is_estimated"])
            self.assertGreater(data["total_seconds"], 1.0)
            chapter_titles = [ch["title"] for ch in data["chapters"]]
            self.assertEqual(chapter_titles, ["Set 1", "Rest after Set 1", "Set 2", "Complete"])

    def test_preview_only_timestamps_export_without_audio(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_lrc = Path(tmpdir) / "plan.lrc"
            cli.main(
                [
                    "--preset",
                    "tabata",
                    "--timestamps-file",
                    str(out_lrc),
                ]
            )
            self.assertTrue(out_lrc.exists())
            text = out_lrc.read_text(encoding="utf-8")
            self.assertIn("Round 1", text)
            self.assertIn("Workout complete", text)

    def test_audio_metadata_tags_passed_for_compressed_formats(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_mp3 = Path(tmpdir) / "workout.mp3"
            mock_audio = MagicMock()
            tags = {"title": "My Session", "artist": "Workout Audio Coach"}
            with patch("workout_audio_coach.audio.ensure_ffmpeg_available"):
                audio.export_workout_audio(mock_audio, out_mp3, "mp3", tags=tags)
            mock_audio.export.assert_called_once_with(out_mp3, format="mp3", tags=tags)


if __name__ == "__main__":
    unittest.main()
