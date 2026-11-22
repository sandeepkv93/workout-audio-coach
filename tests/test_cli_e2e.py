from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import workout_audio_coach

REPO_ROOT = Path(__file__).resolve().parent.parent


class EndToEndCLITests(unittest.TestCase):
    def test_module_entrypoint_version_flag(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "workout_audio_coach", "--version"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn(workout_audio_coach.__version__, result.stdout)

    def test_backward_compatible_script_shim(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "sets_and_reps_counter.py",
                "--reps",
                "3",
                "--sets",
                "2",
                "--rep-gap",
                "1",
                "--set-gap",
                "10",
                "--preview",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("Sets x reps: 2 x 3", result.stdout)
        self.assertIn("Workout complete", result.stdout)

    def test_no_cache_does_not_create_cache_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_dir = root / "cache"
            out_wav = root / "session.wav"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "workout_audio_coach",
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
                    "--cache-dir",
                    str(cache_dir),
                    "--output-file",
                    str(out_wav),
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertTrue(out_wav.exists())
            self.assertFalse(cache_dir.exists())


if __name__ == "__main__":
    unittest.main()
