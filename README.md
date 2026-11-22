# Workout Audio Coach

[![CI](https://github.com/sandeepkv93/workout-audio-coach/actions/workflows/ci.yml/badge.svg)](https://github.com/sandeepkv93/workout-audio-coach/actions/workflows/ci.yml)
[![Live Web App](https://img.shields.io/badge/web%20app-GitHub%20Pages-38bdf8.svg)](https://sandeepkv93.github.io/workout-audio-coach/)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

> **Try it in your browser:** [Workout Audio Coach Web Player & Routine Builder](https://sandeepkv93.github.io/workout-audio-coach/)

`workout-audio-coach` generates guided workout audio, live terminal coaching sessions, and self-contained interactive HTML5 workout players for sets/reps workouts, timed intervals, tempo lifting, and structured multi-exercise circuits.

## Highlights

- **Pure-Python PCM audio engine:** Zero `pydub`/`audioop` dependencies or deprecation warnings; supports $O(N)$ assembly, loudness normalization (`--normalize`), and background music mixing with smooth speech auto-ducking (`--music`, `--duck-db`).
- **Flexible workouts & presets:** Classic `sets × reps`, timed intervals (`--duration`), tempo rep coaching (`--tempo 3-1-1`), pyramid sets, supersets/circuits (`[[circuits]]`), custom TOML/JSON routines (`--routine`), and built-in presets (`tabata`, `emom`, `hiit`, `strength`).
- **Precision coaching cues:** `gap` or fixed-beat `cadence` timing modes, configurable countdown gaps, rest warnings (`--rest-warnings 10,3,2,1`), halfway cues, and last-set cues.
- **Pluggable & offline-capable TTS:** `gtts` (online, with `--tts-tld`/`--tts-slow`), `edge` (optional neural `edge-tts`), `piper` (offline neural ONNX), `espeak`, macOS `say`, and 100% offline `tone` chimes (zero network and zero `ffmpeg` required for `.wav`), synthesized concurrently (`--tts-workers`) with atomic self-healing caching (`--cache-stats`, `--clear-cache`).
- **Multi-language localization:** Built-in phrase packs (`en`, `es`, `fr`, `de`, `it`, `pt`, `hi`, `ja`, `ko`, `zh`) plus `--phrase KEY=VALUE` overrides.
- **Live & interactive outputs:** Real-time interactive terminal coach (`--live`), self-contained interactive HTML5 player & visual routine builder (`--export-html`), timestamped cue sheets (`.vtt`, `.srt`, `.lrc`, `.json`), and audio metadata tags (`--title`).

## Setup

Install dependencies with `uv`:

```bash
uv sync
```

## Requirements

- Python 3.12+ (fully compatible with Python 3.13+)
- `ffmpeg` on `PATH` only when decoding/exporting compressed audio formats (`mp3`, `ogg`, `flac`, `m4a`)
- Offline `.wav` export with `--tts-backend tone`, `--preview`, `--live`, and `--export-html` require **zero** external binaries or network access

## Usage

### Classic Sets & Reps with Cadence, Tempo & Coaching Cues

```bash
uv run workout-audio-coach \
  --reps 10 \
  --sets 3 \
  --rep-gap 1.5 \
  --set-gap 30 \
  --timing-mode cadence \
  --rest-warnings 10,3,2,1 \
  --announce-halfway \
  --announce-last-set \
  --normalize \
  --output-file workouts/3x10.mp3

# Tempo lifting (3s eccentric, 1s pause, 1s concentric)
uv run workout-audio-coach \
  --reps 8 --sets 3 --rep-gap 1 --set-gap 45 \
  --tempo 3-1-1 --preview
```

### Background Music with Auto-Ducking

```bash
uv run workout-audio-coach \
  --preset hiit \
  --music tracks/energetic_loop.mp3 \
  --music-gain-db -6 \
  --duck-db -12 \
  --normalize \
  --output-file workouts/hiit_mixed.mp3
```

### Multi-Exercise Routines, Supersets & Built-in Presets

Browse built-in presets or run included examples ([examples/full_body.toml](examples/full_body.toml), [examples/superset_circuit.toml](examples/superset_circuit.toml), [examples/tabata.json](examples/tabata.json)):

```bash
uv run workout-audio-coach --list-presets

uv run workout-audio-coach \
  --routine examples/superset_circuit.toml \
  --script-file plans/superset.txt \
  --timestamps-file workouts/superset.vtt \
  --output-file workouts/superset.mp3
```

### Interactive Live Terminal Coach & HTML5 Web Player/Builder

```bash
# Run live in the terminal ([Space] Pause, [N] Skip, [Q] Quit)
uv run workout-audio-coach --preset tabata --tts-backend tone --live

# Export a self-contained HTML5 player + visual routine builder (works offline in any browser)
uv run workout-audio-coach --routine examples/full_body.toml --export-html player.html
```

### Neural & Offline TTS Backends + Cache Management

```bash
# 100% offline synthesized chimes (no network, no ffmpeg needed for WAV)
uv run workout-audio-coach --preset tabata --tts-backend tone --output-file workouts/tabata.wav

# Neural voices via optional edge-tts or local piper ONNX model
uv run workout-audio-coach --preset tabata --tts-backend edge --tts-voice en-US-GuyNeural --output-file workouts/tabata.mp3
uv run workout-audio-coach --preset tabata --tts-backend piper --tts-voice /path/to/voice.onnx --output-file workouts/tabata.wav

# Inspect or clear cached clips
uv run workout-audio-coach --cache-stats
uv run workout-audio-coach --clear-cache
```

### Localization & Custom Phrases

```bash
uv run workout-audio-coach \
  --reps 8 --sets 3 --rep-gap 1 --set-gap 20 \
  --language es \
  --phrase "workout_complete=¡Excelente trabajo!" \
  --preview
```

Backward-compatible script usage still works:

```bash
uv run python sets_and_reps_counter.py --reps 10 --sets 3 --rep-gap 1 --set-gap 30 --preview
```

## Development

Run linting, formatting, strict type checking, tests, and package build:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict workout_audio_coach tests sets_and_reps_counter.py
uv run pytest -v
uv run python -m unittest discover -s tests -v
uv build
```

See [CHANGELOG.md](CHANGELOG.md) for release history and [LICENSE](LICENSE) for MIT license terms.
