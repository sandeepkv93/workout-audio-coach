# Changelog

All notable changes to `workout-audio-coach` are documented in this file.

## [0.3.0] - 2026-11-22

### Added
- **Pure-Python PCM Audio Engine (`PCMAudio`):** Removed `pydub` and `audioop` dependencies entirely, eliminating Python 3.12+ deprecation warnings and `pydub` regex warnings while supporting $O(N)$ concatenation, resampling, channel normalization, and direct `ffmpeg` subprocess calls for compressed formats.
- **Audio Production & Mixing:**
  - Background music looping/trimming with smooth speech auto-ducking (`--music`, `--music-gain-db`, `--duck-db`).
  - Loudness normalization to target RMS dBFS with peak ceiling protection (`--normalize`, `--target-dbfs`).
  - Parallel TTS phrase synthesis (`--tts-workers`) and cache management commands (`--cache-stats`, `--clear-cache`).
  - Optional neural TTS backends: `edge` (`edge-tts` neural voices) and `piper` (offline ONNX neural TTS), plus `espeak`, macOS `say`, and 100% offline `tone` beeps (`--beep-cues`).
- **Smarter Coaching Modes:**
  - Tempo rep coaching (`--tempo 3-1-1` and per-exercise `tempo` in routines) with localized eccentric/pause/concentric cues.
  - Multi-exercise TOML/JSON routines (`--routine`), supersets/circuits (`[[circuits]]`), pyramid rep lists, timed work intervals (`--duration`), and built-in presets (`--preset {tabata,emom,hiit,strength}`, `--list-presets`).
  - Cadence timing mode (`--timing-mode cadence`), configurable countdown gaps, rest warnings (`--rest-warnings 10,3,2,1`), halfway cues, and last-set cues.
  - Real-time interactive terminal coach (`--live`, `--live-silent`) with progress bar and pause/skip/quit controls.
- **Interactive Web Player & Builder:** Self-contained single-file HTML5 workout player and visual routine builder (`--export-html`) powered by Web Speech API and Web Audio API with routine JSON export.
- **Localization, Timelines & Metadata:**
  - Multi-language phrase packs (`en`, `es`, `fr`, `de`, `it`, `pt`, `hi`, `ja`, `ko`, `zh`) plus `--phrase KEY=VALUE` overrides.
  - Duration estimation in previews, timestamped cue sheets (`.vtt`, `.srt`, `.lrc`, `.json`), and embedded audio metadata tags (`--title`).
- **Engineering & CI:** Modular package architecture, 100% strict `mypy --strict` + `ruff` typing/lint coverage, PEP 561 `py.typed`, GitHub Actions CI & Release workflows, and MIT `LICENSE`.

## [0.2.0]

- Initial `workout-audio-coach` refactor from `sets_and_reps_counter.py` with `uv`, preview mode, speech clip caching, retry backoff, and baseline unit tests.
