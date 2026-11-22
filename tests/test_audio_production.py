from __future__ import annotations

import io
import tempfile
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from workout_audio_coach import audio, cli, config, pcm, tones, tts


class _ThreadSafeToneBackend:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.phrases_seen: list[str] = []

    @property
    def name(self) -> str:
        return "mock-neural"

    @property
    def file_extension(self) -> str:
        return "wav"

    def cache_namespace(self) -> str:
        return "mock-neural:v1"

    def synthesize(
        self,
        phrase: str,
        language: str,
        *,
        kind: config.StepKind = "cue",
    ) -> bytes:
        del language, kind
        with self._lock:
            self.phrases_seen.append(phrase)
        return tones.synthesize_tone_wav([(440.0, 0.1)], volume=0.2)


class AudioProductionTests(unittest.TestCase):
    def test_loudness_normalization_hits_target_dbfs_without_clipping(self) -> None:
        quiet = pcm.PCMAudio.from_wav_bytes(tones.synthesize_tone_wav([(440.0, 0.2)], volume=0.05))
        loud = pcm.PCMAudio.from_wav_bytes(tones.synthesize_tone_wav([(440.0, 0.2)], volume=0.9))

        self.assertLess(quiet.rms_dbfs(), -25.0)
        norm_quiet = quiet.normalize_dbfs(-16.0)
        norm_loud = loud.normalize_dbfs(-16.0)

        self.assertAlmostEqual(norm_quiet.rms_dbfs(), -16.0, delta=0.8)
        self.assertAlmostEqual(norm_loud.rms_dbfs(), -16.0, delta=0.8)
        self.assertLessEqual(norm_quiet.peak_amplitude(), pcm.MAX_INT16)

    def test_background_music_loops_and_ducks_during_speech(self) -> None:
        # 2.0s silent voice track with speech marked from 1000ms..1600ms
        voice = pcm.PCMAudio.silent(2000, frame_rate=24000)
        # 0.4s constant tone music clip (must loop 5x to cover 2.0s)
        music = pcm.PCMAudio.from_wav_bytes(tones.synthesize_tone_wav([(330.0, 0.4)], volume=0.5))

        mixed = pcm.mix_background_music(
            voice,
            music,
            speech_ranges_ms=[(1000, 1600)],
            music_gain_db=-6.0,
            duck_db=-12.0,
            attack_ms=40,
            release_ms=40,
            fade_out_ms=0,
        )
        self.assertEqual(len(mixed), 2000)

        # Compare RMS in unducked region (200ms..800ms) vs ducked region (1150ms..1500ms)
        frame_bytes = mixed.channels * mixed.sample_width
        unducked = pcm.PCMAudio(
            raw_data=mixed.raw_data[
                round(0.2 * mixed.frame_rate) * frame_bytes : round(0.8 * mixed.frame_rate)
                * frame_bytes
            ],
            frame_rate=mixed.frame_rate,
            channels=mixed.channels,
        )
        ducked = pcm.PCMAudio(
            raw_data=mixed.raw_data[
                round(1.15 * mixed.frame_rate) * frame_bytes : round(1.5 * mixed.frame_rate)
                * frame_bytes
            ],
            frame_rate=mixed.frame_rate,
            channels=mixed.channels,
        )
        # Expect roughly ~12 dB reduction during speech
        self.assertGreater(unducked.rms_dbfs() - ducked.rms_dbfs(), 9.0)

    def test_parallel_tts_and_normalization_and_music_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            music_wav = root / "loop.wav"
            music_wav.write_bytes(tones.synthesize_tone_wav([(220.0, 0.25)], volume=0.4))
            out_wav = root / "mixed.wav"
            cache_dir = root / "cache"

            cli.main(
                [
                    "--reps",
                    "3",
                    "--sets",
                    "2",
                    "--rep-gap",
                    "0.2",
                    "--set-gap",
                    "0.4",
                    "--countdown",
                    "1",
                    "--tts-backend",
                    "tone",
                    "--tts-workers",
                    "4",
                    "--normalize",
                    "--target-dbfs",
                    "-15",
                    "--music",
                    str(music_wav),
                    "--music-gain-db",
                    "-8",
                    "--duck-db",
                    "-10",
                    "--cache-dir",
                    str(cache_dir),
                    "--output-file",
                    str(out_wav),
                ]
            )
            self.assertTrue(out_wav.exists())
            loaded = pcm.PCMAudio.from_file(out_wav)
            self.assertGreater(len(loaded), 1000)

            # Check cache stats & clear cache CLI commands
            stats_buf = io.StringIO()
            with redirect_stdout(stats_buf):
                cli.main(["--cache-dir", str(cache_dir), "--cache-stats"])
            self.assertIn("Cached clips:", stats_buf.getvalue())
            self.assertGreater(tts.get_cache_stats(cache_dir).file_count, 0)

            clear_buf = io.StringIO()
            with redirect_stdout(clear_buf):
                cli.main(["--cache-dir", str(cache_dir), "--clear-cache"])
            self.assertIn("Cleared", clear_buf.getvalue())
            self.assertEqual(tts.get_cache_stats(cache_dir).file_count, 0)

    def test_parallel_synthesis_with_thread_pool(self) -> None:
        backend = _ThreadSafeToneBackend()
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = config.WorkoutConfig(
                reps=5,
                sets=2,
                rep_gap=0.1,
                set_gap=0.2,
                output_file=None,
                output_format=None,
                language="en",
                cache_dir=Path(tmpdir),
                use_cache=True,
                countdown=2,
                announce_rest=True,
                set_start_gap=0.1,
                preview=False,
                script_file=None,
                tts_attempts=1,
                tts_initial_backoff=0.1,
                tts_workers=4,
                normalize_audio=True,
            )
            combined, timeline = audio.build_workout_audio_with_timeline(cfg, backend=backend)
            self.assertGreater(len(combined), 500)
            self.assertGreater(len(timeline.entries), 10)
            self.assertGreaterEqual(len(set(backend.phrases_seen)), 8)

    def test_edge_and_piper_backends_validation(self) -> None:
        edge = tts.EdgeTTSBackend()
        self.assertEqual(edge.resolve_voice("es-MX"), "es-ES-AlvaroNeural")
        self.assertEqual(edge.resolve_voice("en"), "en-US-GuyNeural")
        self.assertEqual(
            tts.EdgeTTSBackend(voice="en-GB-RyanNeural").resolve_voice("en"), "en-GB-RyanNeural"
        )

        with (
            patch("workout_audio_coach.tts.shutil.which", return_value=None),
            self.assertRaisesRegex(RuntimeError, "edge-tts"),
        ):
            edge.synthesize("Set 1", "en")

        with (
            patch("workout_audio_coach.tts.shutil.which", return_value=None),
            self.assertRaisesRegex(RuntimeError, "piper"),
        ):
            tts.PiperBackend(model="voice.onnx").synthesize("Set 1", "en")

        with (
            patch("workout_audio_coach.tts.shutil.which", return_value="/usr/bin/piper"),
            self.assertRaisesRegex(RuntimeError, "--tts-voice"),
        ):
            tts.PiperBackend(model=None).synthesize("Set 1", "en")


if __name__ == "__main__":
    unittest.main()
