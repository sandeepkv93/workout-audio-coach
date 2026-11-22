from __future__ import annotations

import json
import math
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from workout_audio_coach.config import SUPPORTED_TIMING_MODES, TimingMode, parse_rest_warnings
from workout_audio_coach.localization import VALID_PHRASE_KEYS


@dataclass(frozen=True)
class ExerciseSpec:
    name: str
    sets: int = 1
    reps: int | tuple[int, ...] | None = None
    duration: float | None = None
    rep_gap: float = 1.0
    set_gap: float = 30.0
    set_start_gap: float = 1.0
    rest_after: float | None = None

    def rep_counts(self) -> tuple[int, ...] | None:
        if self.reps is None:
            return None
        if isinstance(self.reps, int):
            return tuple(self.reps for _ in range(self.sets))
        return self.reps

    def total_sets(self) -> int:
        if isinstance(self.reps, tuple):
            return len(self.reps)
        return self.sets


@dataclass(frozen=True)
class WorkoutRoutine:
    name: str
    exercises: tuple[ExerciseSpec, ...]
    exercise_gap: float = 30.0
    countdown: int | None = None
    language: str | None = None
    timing_mode: TimingMode | None = None
    announce_rest: bool | None = None
    rest_warnings: tuple[int, ...] | None = None
    announce_halfway: bool | None = None
    announce_last_set: bool | None = None
    phrase_overrides: tuple[tuple[str, str], ...] = ()


BUILTIN_PRESETS: dict[str, WorkoutRoutine] = {
    "tabata": WorkoutRoutine(
        name="Tabata 4-Minute Interval",
        exercises=(
            ExerciseSpec(
                name="Work",
                sets=8,
                duration=20.0,
                set_gap=10.0,
                set_start_gap=0.5,
            ),
        ),
        countdown=3,
        timing_mode="cadence",
        announce_rest=True,
        rest_warnings=(3, 2, 1),
        announce_halfway=True,
        announce_last_set=True,
    ),
    "emom": WorkoutRoutine(
        name="EMOM 10-Minute Conditioning",
        exercises=(
            ExerciseSpec(
                name="Minute Interval",
                sets=10,
                duration=45.0,
                set_gap=15.0,
                set_start_gap=0.5,
            ),
        ),
        countdown=3,
        timing_mode="cadence",
        announce_rest=True,
        rest_warnings=(10, 3, 2, 1),
        announce_halfway=True,
        announce_last_set=True,
    ),
    "hiit": WorkoutRoutine(
        name="Full Body HIIT Circuit",
        exercises=(
            ExerciseSpec(name="Jumping Jacks", sets=3, duration=30.0, set_gap=15.0),
            ExerciseSpec(name="Push-ups", sets=3, duration=30.0, set_gap=15.0),
            ExerciseSpec(name="Bodyweight Squats", sets=3, duration=30.0, set_gap=15.0),
            ExerciseSpec(name="Plank", sets=3, duration=30.0, set_gap=15.0),
        ),
        exercise_gap=30.0,
        countdown=3,
        timing_mode="cadence",
        announce_rest=True,
        rest_warnings=(10, 3, 2, 1),
        announce_halfway=True,
        announce_last_set=True,
    ),
    "strength": WorkoutRoutine(
        name="Bodyweight Pyramid Strength",
        exercises=(
            ExerciseSpec(name="Push-ups", reps=(12, 10, 8), rep_gap=1.5, set_gap=45.0),
            ExerciseSpec(name="Squats", reps=(15, 12, 10), rep_gap=1.5, set_gap=45.0),
            ExerciseSpec(name="Plank", sets=3, duration=45.0, set_gap=30.0),
        ),
        exercise_gap=60.0,
        countdown=3,
        announce_rest=True,
        rest_warnings=(10, 3, 2, 1),
        announce_halfway=True,
        announce_last_set=True,
    ),
}

PRESET_NAMES: tuple[str, ...] = tuple(BUILTIN_PRESETS.keys())


def get_preset_routine(name: str) -> WorkoutRoutine:
    key = name.strip().lower()
    if key not in BUILTIN_PRESETS:
        available = ", ".join(PRESET_NAMES)
        raise ValueError(f"unknown preset {name!r}; available presets: {available}")
    return BUILTIN_PRESETS[key]


def format_preset_list() -> str:
    lines = ["Available workout presets:", ""]
    for key, routine in BUILTIN_PRESETS.items():
        exercise_summary = ", ".join(ex.name for ex in routine.exercises)
        lines.append(f"  {key:<10} {routine.name} ({exercise_summary})")
    return "\n".join(lines)


def _require_positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _require_non_negative_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _require_non_negative_float(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a non-negative number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{field_name} must be a finite non-negative number")
    return parsed


def _require_positive_float(value: object, field_name: str) -> float:
    parsed = _require_non_negative_float(value, field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return parsed


def _parse_exercise(raw: object, index: int) -> ExerciseSpec:
    if not isinstance(raw, Mapping):
        raise ValueError(f"exercises[{index}] must be a mapping/table")

    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"exercises[{index}].name must be a non-empty string")

    raw_reps = raw.get("reps")
    raw_duration = raw.get("duration")
    if raw_reps is None and raw_duration is None:
        raise ValueError(f"exercises[{index}] ({name!r}) must specify either 'reps' or 'duration'")
    if raw_reps is not None and raw_duration is not None:
        raise ValueError(f"exercises[{index}] ({name!r}) cannot specify both 'reps' and 'duration'")

    parsed_reps: int | tuple[int, ...] | None = None
    inferred_sets: int | None = None
    if raw_reps is not None:
        if isinstance(raw_reps, list):
            if not raw_reps:
                raise ValueError(f"exercises[{index}].reps list cannot be empty")
            parsed_reps = tuple(
                _require_positive_int(item, f"exercises[{index}].reps[{i}]")
                for i, item in enumerate(raw_reps)
            )
            inferred_sets = len(parsed_reps)
        else:
            parsed_reps = _require_positive_int(raw_reps, f"exercises[{index}].reps")

    parsed_duration: float | None = None
    if raw_duration is not None:
        parsed_duration = _require_positive_float(raw_duration, f"exercises[{index}].duration")

    raw_sets = raw.get("sets")
    if raw_sets is not None:
        sets = _require_positive_int(raw_sets, f"exercises[{index}].sets")
        if inferred_sets is not None and sets != inferred_sets:
            raise ValueError(
                f"exercises[{index}].sets ({sets}) does not match length of reps ({inferred_sets})"
            )
    else:
        sets = inferred_sets if inferred_sets is not None else 1

    rep_gap = (
        _require_non_negative_float(raw["rep_gap"], f"exercises[{index}].rep_gap")
        if "rep_gap" in raw
        else 1.0
    )
    set_gap = (
        _require_non_negative_float(raw["set_gap"], f"exercises[{index}].set_gap")
        if "set_gap" in raw
        else 30.0
    )
    set_start_gap = (
        _require_non_negative_float(raw["set_start_gap"], f"exercises[{index}].set_start_gap")
        if "set_start_gap" in raw
        else 1.0
    )
    rest_after = (
        _require_non_negative_float(raw["rest_after"], f"exercises[{index}].rest_after")
        if "rest_after" in raw and raw["rest_after"] is not None
        else None
    )

    return ExerciseSpec(
        name=name.strip(),
        sets=sets,
        reps=parsed_reps,
        duration=parsed_duration,
        rep_gap=rep_gap,
        set_gap=set_gap,
        set_start_gap=set_start_gap,
        rest_after=rest_after,
    )


def parse_routine_dict(
    data: Mapping[str, object], *, default_name: str = "Workout"
) -> WorkoutRoutine:
    raw_name = data.get("name", default_name)
    if not isinstance(raw_name, str) or not raw_name.strip():
        raise ValueError("routine 'name' must be a non-empty string")

    raw_exercises = data.get("exercises")
    if not isinstance(raw_exercises, list) or not raw_exercises:
        raise ValueError("routine must define a non-empty 'exercises' list")

    exercises = tuple(_parse_exercise(item, idx) for idx, item in enumerate(raw_exercises))

    exercise_gap = (
        _require_non_negative_float(data["exercise_gap"], "exercise_gap")
        if "exercise_gap" in data
        else 30.0
    )
    countdown = (
        _require_non_negative_int(data["countdown"], "countdown")
        if "countdown" in data and data["countdown"] is not None
        else None
    )

    language: str | None = None
    if "language" in data and data["language"] is not None:
        raw_lang = data["language"]
        if not isinstance(raw_lang, str) or not raw_lang.strip():
            raise ValueError("routine 'language' must be a non-empty string")
        language = raw_lang.strip()

    timing_mode: TimingMode | None = None
    if "timing_mode" in data and data["timing_mode"] is not None:
        raw_mode = data["timing_mode"]
        if not isinstance(raw_mode, str) or raw_mode not in SUPPORTED_TIMING_MODES:
            raise ValueError(f"routine 'timing_mode' must be one of {SUPPORTED_TIMING_MODES}")
        timing_mode = "cadence" if raw_mode == "cadence" else "gap"

    announce_rest: bool | None = None
    if "announce_rest" in data and data["announce_rest"] is not None:
        if not isinstance(data["announce_rest"], bool):
            raise ValueError("routine 'announce_rest' must be a boolean")
        announce_rest = data["announce_rest"]

    announce_halfway: bool | None = None
    if "announce_halfway" in data and data["announce_halfway"] is not None:
        if not isinstance(data["announce_halfway"], bool):
            raise ValueError("routine 'announce_halfway' must be a boolean")
        announce_halfway = data["announce_halfway"]

    announce_last_set: bool | None = None
    if "announce_last_set" in data and data["announce_last_set"] is not None:
        if not isinstance(data["announce_last_set"], bool):
            raise ValueError("routine 'announce_last_set' must be a boolean")
        announce_last_set = data["announce_last_set"]

    rest_warnings: tuple[int, ...] | None = None
    if "rest_warnings" in data and data["rest_warnings"] is not None:
        raw_rw = data["rest_warnings"]
        if isinstance(raw_rw, str):
            rest_warnings = parse_rest_warnings(raw_rw)
        elif isinstance(raw_rw, list):
            parsed_list = [
                _require_positive_int(item, f"rest_warnings[{i}]") for i, item in enumerate(raw_rw)
            ]
            rest_warnings = tuple(sorted(set(parsed_list), reverse=True))
        else:
            raise ValueError("routine 'rest_warnings' must be a list of ints or comma string")

    phrase_overrides: list[tuple[str, str]] = []
    if "phrases" in data and data["phrases"] is not None:
        raw_phrases = data["phrases"]
        if not isinstance(raw_phrases, Mapping):
            raise ValueError("routine 'phrases' must be a mapping")
        for key, value in raw_phrases.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise ValueError("routine 'phrases' keys and values must be strings")
            normalized = key.strip().replace("-", "_")
            if normalized not in VALID_PHRASE_KEYS:
                valid = ", ".join(sorted(VALID_PHRASE_KEYS))
                raise ValueError(f"unknown phrase key {key!r}; valid keys: {valid}")
            phrase_overrides.append((normalized, value))

    return WorkoutRoutine(
        name=raw_name.strip(),
        exercises=exercises,
        exercise_gap=exercise_gap,
        countdown=countdown,
        language=language,
        timing_mode=timing_mode,
        announce_rest=announce_rest,
        rest_warnings=rest_warnings,
        announce_halfway=announce_halfway,
        announce_last_set=announce_last_set,
        phrase_overrides=tuple(phrase_overrides),
    )


def load_routine_file(path: Path) -> WorkoutRoutine:
    if not path.exists():
        raise ValueError(f"routine file not found: {path}")
    raw_text = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    parsed: object
    if suffix == ".toml":
        parsed = tomllib.loads(raw_text)
    elif suffix == ".json":
        parsed = json.loads(raw_text)
    else:
        raise ValueError(
            f"unsupported routine file extension {suffix!r}; supported formats: .toml, .json"
        )
    if not isinstance(parsed, Mapping):
        raise ValueError("routine file root must be a JSON object or TOML table")
    return parse_routine_dict(parsed, default_name=path.stem)
