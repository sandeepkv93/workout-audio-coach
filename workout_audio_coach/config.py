from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from workout_audio_coach.routines import WorkoutRoutine

DEFAULT_SET_START_GAP_SECONDS: float = 1.0
DEFAULT_COUNTDOWN_GAP_SECONDS: float = 1.0
SUPPORTED_OUTPUT_FORMATS: tuple[str, ...] = ("mp3", "wav", "ogg", "flac", "m4a")
SUPPORTED_TIMING_MODES: tuple[str, ...] = ("gap", "cadence")
SUPPORTED_TTS_BACKENDS: tuple[str, ...] = ("gtts", "edge", "piper", "espeak", "say", "tone")

TimingMode = Literal["gap", "cadence"]
TTSBackendName = Literal["gtts", "edge", "piper", "espeak", "say", "tone"]
StepKind = Literal[
    "countdown",
    "set",
    "rep",
    "rest",
    "cue",
    "exercise",
    "complete",
    "silence",
]


@dataclass(frozen=True)
class TempoSpec:
    eccentric: int
    pause: int
    concentric: int
    top_pause: int = 0

    def label(self) -> str:
        if self.top_pause > 0:
            return f"{self.eccentric}-{self.pause}-{self.concentric}-{self.top_pause}"
        return f"{self.eccentric}-{self.pause}-{self.concentric}"


def parse_tempo(raw: str) -> TempoSpec:
    parts = [token.strip() for token in raw.split("-")]
    if len(parts) not in (3, 4):
        raise ValueError(
            f"invalid tempo {raw!r}; expected ECC-PAUSE-CONC or ECC-PAUSE-CONC-TOP (e.g. '3-1-1')"
        )
    try:
        values = [int(p) for p in parts]
    except ValueError as exc:
        raise ValueError(f"invalid tempo {raw!r}; all phases must be integers") from exc
    if any(v < 0 for v in values):
        raise ValueError(f"invalid tempo {raw!r}; phase durations must be 0 or greater")
    if values[0] <= 0 or values[2] <= 0:
        raise ValueError(f"invalid tempo {raw!r}; eccentric and concentric phases must be > 0")
    top_pause = values[3] if len(values) == 4 else 0
    return TempoSpec(
        eccentric=values[0],
        pause=values[1],
        concentric=values[2],
        top_pause=top_pause,
    )


@dataclass(frozen=True)
class WorkoutConfig:
    reps: int
    sets: int
    rep_gap: float
    set_gap: float
    output_file: Path | None
    output_format: str | None
    language: str
    cache_dir: Path
    use_cache: bool
    countdown: int
    announce_rest: bool
    set_start_gap: float
    preview: bool
    script_file: Path | None
    tts_attempts: int
    tts_initial_backoff: float
    phrase_overrides: tuple[tuple[str, str], ...] = ()
    timing_mode: TimingMode = "gap"
    countdown_gap: float = DEFAULT_COUNTDOWN_GAP_SECONDS
    countdown_end_gap: float = 0.0
    rest_warnings: tuple[int, ...] = ()
    announce_halfway: bool = False
    announce_last_set: bool = False
    tts_backend: TTSBackendName = "gtts"
    tts_tld: str = "com"
    tts_slow: bool = False
    tts_voice: str | None = None
    beep_cues: bool = False
    duration: float | None = None
    routine: WorkoutRoutine | None = None
    timestamps_file: Path | None = None
    title: str | None = None
    normalize_audio: bool = False
    target_dbfs: float = -16.0
    music_file: Path | None = None
    music_gain_db: float = -6.0
    duck_db: float = -12.0
    tts_workers: int = 4
    tempo: TempoSpec | None = None
    live: bool = False
    live_silent: bool = False


@dataclass(frozen=True)
class WorkoutStep:
    spoken_text: str | None
    gap_after: float = 0.0
    target_interval: float | None = None
    kind: StepKind = field(default="cue", compare=False)
    section: str | None = field(default=None, compare=False)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than 0")
    return parsed


def non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("value must be 0 or greater")
    return parsed


def finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("value must be a finite number")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("value must be a finite number greater than 0")
    return parsed


def non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("value must be a finite number 0 or greater")
    return parsed


def parse_rest_warnings(raw: str) -> tuple[int, ...]:
    if not raw.strip():
        return ()
    values: set[int] = set()
    for token in raw.split(","):
        stripped = token.strip()
        if not stripped:
            continue
        parsed = int(stripped)
        if parsed <= 0:
            raise ValueError("rest warning timestamps must be positive integers")
        values.add(parsed)
    return tuple(sorted(values, reverse=True))


def default_cache_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "workout-audio-coach"
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "workout-audio-coach"
    xdg_cache_home = os.environ.get("XDG_CACHE_HOME")
    if xdg_cache_home:
        return Path(xdg_cache_home) / "workout-audio-coach"
    return Path.home() / ".cache" / "workout-audio-coach"


def resolve_output_format(output_file: Path | None, explicit_format: str | None) -> str | None:
    if output_file is None:
        if explicit_format:
            raise ValueError("--format requires --output-file")
        return None

    if explicit_format:
        normalized = explicit_format.lower()
        if normalized not in SUPPORTED_OUTPUT_FORMATS:
            supported = ", ".join(SUPPORTED_OUTPUT_FORMATS)
            raise ValueError(
                f"unsupported output format {explicit_format!r}; choose from: {supported}"
            )
        return normalized

    suffix = output_file.suffix.lower().lstrip(".")
    if not suffix:
        return "mp3"
    if suffix in SUPPORTED_OUTPUT_FORMATS:
        return suffix
    supported = ", ".join(SUPPORTED_OUTPUT_FORMATS)
    raise ValueError(
        f"unsupported output file extension '.{suffix}'; "
        f"use one of ({supported}) or pass --format explicitly"
    )
