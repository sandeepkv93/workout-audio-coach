from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SET_START_GAP_SECONDS: float = 1.0
DEFAULT_COUNTDOWN_GAP_SECONDS: float = 1.0
SUPPORTED_OUTPUT_FORMATS: tuple[str, ...] = ("mp3", "wav", "ogg", "flac", "m4a")


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


@dataclass(frozen=True)
class WorkoutStep:
    spoken_text: str | None
    gap_after: float = 0.0


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
