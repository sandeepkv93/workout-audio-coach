from __future__ import annotations

import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from workout_audio_coach import audio, cli, config, tones, tts
from workout_audio_coach.pcm import PCMAudio as AudioSegment


class ToneSynthesizerTests(unittest.TestCase):
    def test_synthesize_tone_wav_produces_valid_pcm_wav(self) -> None:
        wav_bytes = tones.synthesize_tone_wav([(440.0, 0.1), (0.0, 0.05), (880.0, 0.1)])
        seg = tones.wav_bytes_to_segment(wav_bytes)
        self.assertEqual(seg.channels, 1)
        self.assertEqual(seg.sample_width, 2)
        self.assertEqual(seg.frame_rate, tones.DEFAULT_SAMPLE_RATE)
        self.assertEqual(len(seg), 250)

    def test_synthesize_tone_wav_rejects_invalid_volume(self) -> None:
        with self.assertRaisesRegex(ValueError, "volume"):
            tones.synthesize_tone_wav([(440.0, 0.1)], volume=1.5)


class TTSBackendTests(unittest.TestCase):
    def test_cache_namespace_separates_backend_and_options(self) -> None:
        cache_dir = Path("cache")
        default_path = tts.phrase_cache_path(cache_dir, "Rest", "en")
        uk_backend = tts.create_tts_backend("gtts", tld="co.uk", slow=True)
        uk_path = tts.phrase_cache_path(
            cache_dir,
            "Rest",
            "en",
            namespace=uk_backend.cache_namespace(),
            extension=uk_backend.file_extension,
        )
        tone_backend = tts.create_tts_backend("tone")
        tone_path = tts.phrase_cache_path(
            cache_dir,
            "Rest",
            "en",
            namespace=tone_backend.cache_namespace(),
            extension=tone_backend.file_extension,
        )
        self.assertNotEqual(default_path, uk_path)
        self.assertNotEqual(default_path, tone_path)
        self.assertEqual(tone_path.suffix, ".wav")

    def test_espeak_and_say_backends_report_missing_binary(self) -> None:
        with patch("workout_audio_coach.tts.shutil.which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "espeak"):
                tts.EspeakBackend().synthesize("Set 1", "en")
            with self.assertRaisesRegex(RuntimeError, "macOS 'say'"):
                tts.MacOSSayBackend().synthesize("Set 1", "en")

    def test_tone_backend_generates_offline_wav_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_wav = Path(tmpdir) / "offline_workout.wav"
            cache_dir = Path(tmpdir) / "cache"
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
                    "1",
                    "--set-start-gap",
                    "0.1",
                    "--tts-backend",
                    "tone",
                    "--cache-dir",
                    str(cache_dir),
                    "--output-file",
                    str(out_wav),
                ]
            )
            self.assertTrue(out_wav.exists())
            with wave.open(str(out_wav), "rb") as handle:
                self.assertEqual(handle.getnchannels(), 1)
                self.assertEqual(handle.getsampwidth(), 2)
                self.assertGreater(handle.getnframes(), 0)

    def test_beep_cues_prepend_tones_to_key_steps(self) -> None:
        cfg_without = config.WorkoutConfig(
            reps=2,
            sets=1,
            rep_gap=0.5,
            set_gap=0.0,
            output_file=None,
            output_format=None,
            language="en",
            cache_dir=Path("cache"),
            use_cache=False,
            countdown=0,
            announce_rest=True,
            set_start_gap=0.0,
            preview=False,
            script_file=None,
            tts_attempts=1,
            tts_initial_backoff=0.1,
            beep_cues=False,
        )
        cfg_with = config.WorkoutConfig(
            reps=2,
            sets=1,
            rep_gap=0.5,
            set_gap=0.0,
            output_file=None,
            output_format=None,
            language="en",
            cache_dir=Path("cache"),
            use_cache=False,
            countdown=0,
            announce_rest=True,
            set_start_gap=0.0,
            preview=False,
            script_file=None,
            tts_attempts=1,
            tts_initial_backoff=0.1,
            beep_cues=True,
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
            return AudioSegment.silent(duration=100, frame_rate=tones.DEFAULT_SAMPLE_RATE)

        without_beeps = audio.build_workout_audio(cfg_without, segment_loader=fake_loader)
        with_beeps = audio.build_workout_audio(cfg_with, segment_loader=fake_loader)

        # Set 1 chime (~260ms) + Workout complete arpeggio (~420ms) added
        self.assertGreater(len(with_beeps), len(without_beeps) + 500)


if __name__ == "__main__":
    unittest.main()
