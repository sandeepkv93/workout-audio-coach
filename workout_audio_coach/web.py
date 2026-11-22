from __future__ import annotations

import html
import json
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path

from workout_audio_coach.config import WorkoutConfig, WorkoutStep, default_cache_dir
from workout_audio_coach.planner import build_workout_plan
from workout_audio_coach.routines import BUILTIN_PRESETS, WorkoutRoutine
from workout_audio_coach.timeline import (
    WorkoutTimeline,
    build_estimated_timeline,
    format_duration,
)


def _safe_json_for_script(payload: object) -> str:
    """Serialize JSON safely for inline HTML <script> embedding."""
    raw = json.dumps(payload, ensure_ascii=False)
    return (
        raw.replace("</", "<\\/")
        .replace("<!--", "<\\!--")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _exercises_payload_from_routine(routine: WorkoutRoutine) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for ex in routine.exercises:
        reps_val = ex.reps[0] if isinstance(ex.reps, tuple) else ex.reps
        items.append(
            {
                "name": ex.name,
                "mode": "duration" if ex.duration is not None else "reps",
                "sets": ex.total_sets(),
                "reps": reps_val if reps_val is not None else 10,
                "duration": ex.duration if ex.duration is not None else 30.0,
                "rep_gap": ex.rep_gap,
                "set_gap": ex.set_gap,
            }
        )
    for circuit in routine.circuits:
        for ex in circuit.exercises:
            reps_val = ex.reps[0] if isinstance(ex.reps, tuple) else ex.reps
            items.append(
                {
                    "name": f"{circuit.name}: {ex.name}",
                    "mode": "duration" if ex.duration is not None else "reps",
                    "sets": circuit.rounds,
                    "reps": reps_val if reps_val is not None else 10,
                    "duration": ex.duration if ex.duration is not None else 30.0,
                    "rep_gap": ex.rep_gap,
                    "set_gap": circuit.exercise_gap,
                }
            )
    return items


def _build_initial_exercises_payload(config: WorkoutConfig) -> list[dict[str, object]]:
    if config.routine is not None:
        items = _exercises_payload_from_routine(config.routine)
        if items:
            return items

    if config.duration is not None:
        return [
            {
                "name": "Timed Interval",
                "mode": "duration",
                "sets": config.sets,
                "reps": 10,
                "duration": config.duration,
                "rep_gap": 1.0,
                "set_gap": config.set_gap,
            }
        ]

    return [
        {
            "name": config.title or "Workout",
            "mode": "reps",
            "sets": config.sets,
            "reps": config.reps,
            "duration": 30.0,
            "rep_gap": config.rep_gap,
            "set_gap": config.set_gap,
        }
    ]


def _serialize_timeline_steps(timeline: WorkoutTimeline) -> list[dict[str, object]]:
    return [
        {
            "index": entry.index,
            "text": entry.spoken_text,
            "kind": entry.kind,
            "section": entry.section or "Workout",
            "start_seconds": entry.start_seconds,
            "end_seconds": entry.end_seconds,
            "duration_seconds": round(max(0.1, entry.end_seconds - entry.start_seconds), 3),
        }
        for entry in timeline.entries
    ]


def _serialize_chapters(timeline: WorkoutTimeline) -> list[dict[str, object]]:
    return [
        {
            "title": ch.title,
            "start_seconds": ch.start_seconds,
            "end_seconds": ch.end_seconds,
        }
        for ch in timeline.chapters
    ]


def _build_builtin_presets_payload(language: str) -> list[dict[str, object]]:
    presets_payload: list[dict[str, object]] = []
    for key, routine in BUILTIN_PRESETS.items():
        preset_cfg = WorkoutConfig(
            reps=0,
            sets=routine.total_set_count(),
            rep_gap=0.0,
            set_gap=0.0,
            output_file=None,
            output_format=None,
            language=language,
            cache_dir=default_cache_dir(),
            use_cache=False,
            countdown=routine.countdown if routine.countdown is not None else 3,
            announce_rest=routine.announce_rest if routine.announce_rest is not None else True,
            set_start_gap=1.0,
            preview=False,
            script_file=None,
            tts_attempts=1,
            tts_initial_backoff=1.0,
            timing_mode=routine.timing_mode or "gap",
            rest_warnings=routine.rest_warnings or (),
            announce_halfway=bool(routine.announce_halfway),
            announce_last_set=bool(routine.announce_last_set),
            routine=routine,
        )
        preset_plan = build_workout_plan(preset_cfg)
        preset_timeline = build_estimated_timeline(preset_plan)
        presets_payload.append(
            {
                "id": key,
                "title": routine.name,
                "countdown": preset_cfg.countdown,
                "timing_mode": preset_cfg.timing_mode,
                "rest_warnings": list(preset_cfg.rest_warnings),
                "total_seconds": preset_timeline.total_seconds,
                "formatted_duration": format_duration(preset_timeline.total_seconds),
                "chapters": _serialize_chapters(preset_timeline),
                "steps": _serialize_timeline_steps(preset_timeline),
                "exercises": _exercises_payload_from_routine(routine),
            }
        )
    return presets_payload


def render_workout_html(
    config: WorkoutConfig,
    plan: Sequence[WorkoutStep],
    *,
    timeline: WorkoutTimeline | None = None,
) -> str:
    """Render a self-contained interactive HTML5 workout player and routine builder."""
    resolved_timeline = timeline if timeline is not None else build_estimated_timeline(plan)
    workout_title = (
        config.title
        or (config.routine.name if config.routine is not None else None)
        or (
            f"{config.sets} x {config.duration:g}s Intervals"
            if config.duration is not None
            else f"{config.sets} x {config.reps} Workout"
        )
    )

    data_payload = {
        "title": workout_title,
        "language": config.language,
        "countdown": config.countdown,
        "timing_mode": config.timing_mode,
        "announce_rest": config.announce_rest,
        "announce_halfway": config.announce_halfway,
        "announce_last_set": config.announce_last_set,
        "rest_warnings": list(config.rest_warnings),
        "total_seconds": resolved_timeline.total_seconds,
        "formatted_duration": format_duration(resolved_timeline.total_seconds),
        "chapters": _serialize_chapters(resolved_timeline),
        "steps": _serialize_timeline_steps(resolved_timeline),
        "exercises": _build_initial_exercises_payload(config),
        "presets": _build_builtin_presets_payload(config.language),
    }

    template = (
        files("workout_audio_coach")
        .joinpath("templates", "player.html")
        .read_text(encoding="utf-8")
    )
    return template.replace("__WORKOUT_TITLE__", html.escape(workout_title)).replace(
        "__WORKOUT_DATA_JSON__", _safe_json_for_script(data_payload)
    )


def export_workout_html(
    config: WorkoutConfig,
    plan: Sequence[WorkoutStep],
    output_path: Path,
    *,
    timeline: WorkoutTimeline | None = None,
) -> Path:
    html_content = render_workout_html(config, plan, timeline=timeline)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    return output_path
