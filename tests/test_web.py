from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from workout_audio_coach import cli, planner, web


class InteractiveWebPlayerTests(unittest.TestCase):
    def test_export_html_contains_valid_embedded_json_and_ui(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "player.html"
            cli.main(["--preset", "tabata", "--export-html", str(html_path)])
            self.assertTrue(html_path.exists())
            content = html_path.read_text(encoding="utf-8")

            self.assertIn("<!DOCTYPE html>", content)
            self.assertIn("Routine Builder", content)
            self.assertIn("speechSynthesis", content)

            match = re.search(
                r'<script id="workout-data" type="application/json">(.*?)</script>',
                content,
                re.DOTALL,
            )
            self.assertIsNotNone(match)
            assert match is not None
            payload = json.loads(match.group(1))
            self.assertEqual(payload["title"], "Tabata 4-Minute Interval")
            self.assertGreater(len(payload["steps"]), 20)
            self.assertGreater(len(payload["chapters"]), 5)

    def test_render_workout_html_escapes_script_injection(self) -> None:
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
                "5",
                "--title",
                "</script><script>alert(1)</script>",
                "--preview",
            ]
        )
        cfg = cli.build_config(args)
        plan = planner.build_workout_plan(cfg)
        rendered = web.render_workout_html(cfg, plan)

        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertIn("<\\/script>", rendered)

    def test_export_html_alongside_offline_wav_uses_exact_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            out_wav = root / "session.wav"
            out_html = root / "session.html"
            cli.main(
                [
                    "--reps",
                    "2",
                    "--sets",
                    "1",
                    "--rep-gap",
                    "0.1",
                    "--set-gap",
                    "0",
                    "--countdown",
                    "0",
                    "--tts-backend",
                    "tone",
                    "--no-cache",
                    "--output-file",
                    str(out_wav),
                    "--export-html",
                    str(out_html),
                ]
            )
            self.assertTrue(out_wav.exists())
            self.assertTrue(out_html.exists())
            self.assertIn("Workout complete", out_html.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
