# Workout Audio Coach

`workout-audio-coach` generates guided workout audio for sets/reps workouts, timed intervals, and structured multi-exercise routines.

## Features

- **Flexible workouts:** classic `sets × reps`, timed work/rest intervals (`--duration`), built-in presets (`tabata`, `emom`, `hiit`, `strength`), and custom multi-exercise TOML/JSON routines (including pyramid sets).
- **Precision coaching cues:** `gap` or fixed-beat `cadence` timing modes, configurable countdown gaps, rest countdown warnings (`--rest-warnings 10,3,2,1`), halfway cues, and last-set cues.
- **Multi-language localization:** built-in phrase packs (`en`, `es`, `fr`, `de`, `it`, `pt`, `hi`, `ja`, `ko`, `zh`) plus `--phrase KEY=VALUE` overrides.
- **Pluggable & offline-capable audio:** online `gtts` (with accent `--tts-tld` and `--tts-slow`), local offline OS speech (`espeak` / macOS `say`), pure-Python offline `tone` beeps (zero network and zero `ffmpeg` required for `.wav`), and optional `--beep-cues`.
- **Preview, cue sheets & metadata:** print or save text scripts with estimated durations, export timestamped cue sheets (`.vtt`, `.srt`, `.lrc`, `.json`), and embed audio metadata tags.
- **Reliable caching:** atomic, self-healing on-disk speech caching respecting `$XDG_CACHE_HOME`.

## Setup

Install dependencies with `uv`:

```bash
uv sync
```

## Requirements

- Python 3.12+ (Python 3.13+ supported via `audioop-lts`)
- `ffmpeg` on `PATH` when decoding MP3 clips (`gtts`) or exporting compressed formats (`mp3`, `ogg`, `flac`, `m4a`)
- Offline `--tts-backend tone` exporting `.wav` works with zero network access and without `ffmpeg`

## Usage

### Classic Sets & Reps

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
  --output-file workouts/3x10.mp3
```

### Preview Without Generating Audio

```bash
uv run workout-audio-coach \
  --reps 10 \
  --sets 3 \
  --rep-gap 1 \
  --set-gap 30 \
  --preview
```

### Timed Intervals & Built-in Presets

List built-in presets:

```bash
uv run workout-audio-coach --list-presets
```

Run a preset or custom timed interval:

```bash
uv run workout-audio-coach --preset tabata --tts-backend tone --output-file workouts/tabata.wav

uv run workout-audio-coach \
  --duration 45 \
  --sets 4 \
  --set-gap 15 \
  --rest-warnings 3,2,1 \
  --announce-halfway \
  --output-file workouts/plank.wav
```

### Multi-Exercise Routines (TOML / JSON)

See [examples/full_body.toml](examples/full_body.toml) and [examples/tabata.json](examples/tabata.json):

```bash
uv run workout-audio-coach \
  --routine examples/full_body.toml \
  --script-file plans/full_body.txt \
  --timestamps-file workouts/full_body.vtt \
  --output-file workouts/full_body.mp3
```

### Localization & Custom Phrases

```bash
uv run workout-audio-coach \
  --reps 8 \
  --sets 3 \
  --rep-gap 1 \
  --set-gap 20 \
  --language es \
  --phrase "workout_complete=¡Excelente trabajo!" \
  --preview
```

### Offline Audio & Beep Cues

```bash
# Pure offline synthesized chimes/ticks (no internet, no ffmpeg needed for WAV)
uv run workout-audio-coach --preset hiit --tts-backend tone --output-file workouts/hiit.wav

# Local offline speech synthesis (Linux/macOS)
uv run workout-audio-coach --preset tabata --tts-backend espeak --beep-cues --output-file workouts/tabata.wav
```

## Key CLI Options

| Option | Description |
| --- | --- |
| `--routine PATH` | Load a multi-exercise `.toml` or `.json` workout definition |
| `--preset NAME` | Use a built-in preset (`tabata`, `emom`, `hiit`, `strength`) |
| `--duration SECONDS` | Timed work duration per round (alternative to `--reps`) |
| `--timing-mode {gap,cadence}` | Insert trailing silence (`gap`) or lock to fixed intervals (`cadence`) |
| `--rest-warnings CSV` | Seconds remaining to announce during rest (e.g. `10,3,2,1`) |
| `--announce-halfway` / `--announce-last-set` | Toggle midpoint and final-set motivational cues |
| `--language CODE` | Language for TTS and localized cue templates |
| `--phrase KEY=VALUE` | Override any cue template (repeatable) |
| `--tts-backend {gtts,espeak,say,tone}` | Select speech or offline tone synthesis backend |
| `--beep-cues` | Prepend cue tones before countdown, set, rest, and completion cues |
| `--format {mp3,wav,ogg,flac,m4a}` | Explicit output format (inferred from `--output-file` by default) |
| `--timestamps-file PATH` | Export cue sheet / chapters (`.vtt`, `.srt`, `.lrc`, or `.json`) |
| `--title TITLE` | Custom workout title for preview headers and audio metadata tags |
| `--preview` / `--script-file PATH` | Print or save the workout plan without needing audio synthesis |

Backward-compatible script usage still works:

```bash
uv run python sets_and_reps_counter.py --reps 10 --sets 3 --rep-gap 1 --set-gap 30 --preview
```

## Development

Run linting, formatting, strict type checking, and tests:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy workout_audio_coach tests sets_and_reps_counter.py
uv run pytest -v
uv run python -m unittest discover -s tests -v
```

## License

MIT — see [LICENSE](LICENSE).
