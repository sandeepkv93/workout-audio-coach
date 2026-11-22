from __future__ import annotations

from collections.abc import Sequence

from workout_audio_coach.config import (
    TimingMode,
    WorkoutConfig,
    WorkoutStep,
)
from workout_audio_coach.localization import PhrasePack, get_phrase_pack
from workout_audio_coach.routines import ExerciseSpec
from workout_audio_coach.timeline import build_estimated_timeline, format_duration


def build_rest_steps(
    duration_seconds: float,
    *,
    announce_rest: bool,
    phrases: PhrasePack,
    rest_warnings: Sequence[int] = (),
    timing_mode: TimingMode = "gap",
    section: str | None = None,
) -> list[WorkoutStep]:
    """Build steps for a rest period, splitting silence for any configured rest warnings."""
    active_warnings = sorted({w for w in rest_warnings if 0 < w < duration_seconds}, reverse=True)
    steps: list[WorkoutStep] = []

    if not active_warnings:
        if announce_rest:
            steps.append(
                WorkoutStep(
                    spoken_text=phrases.rest,
                    gap_after=duration_seconds,
                    kind="rest",
                    target_interval=duration_seconds if timing_mode == "cadence" else None,
                    section=section,
                )
            )
        elif duration_seconds > 0:
            steps.append(
                WorkoutStep(
                    spoken_text=None,
                    gap_after=duration_seconds,
                    kind="silence",
                    section=section,
                )
            )
        return steps

    first_wait = duration_seconds - active_warnings[0]
    if announce_rest:
        steps.append(
            WorkoutStep(
                spoken_text=phrases.rest,
                gap_after=first_wait,
                kind="rest",
                target_interval=first_wait if timing_mode == "cadence" else None,
                section=section,
            )
        )
    elif first_wait > 0:
        steps.append(
            WorkoutStep(
                spoken_text=None,
                gap_after=first_wait,
                kind="silence",
                section=section,
            )
        )

    for index, seconds_remaining in enumerate(active_warnings):
        next_mark = active_warnings[index + 1] if index + 1 < len(active_warnings) else 0
        span = float(seconds_remaining - next_mark)
        label = (
            str(seconds_remaining)
            if seconds_remaining <= 3
            else phrases.format_seconds_left(seconds_remaining)
        )
        steps.append(
            WorkoutStep(
                spoken_text=label,
                gap_after=span,
                kind="countdown" if seconds_remaining <= 3 else "cue",
                target_interval=span if timing_mode == "cadence" else None,
                section=section,
            )
        )

    return steps


def build_timed_work_steps(
    duration_seconds: float,
    *,
    phrases: PhrasePack,
    announce_halfway: bool = False,
    timing_mode: TimingMode = "gap",
    section: str | None = None,
) -> list[WorkoutStep]:
    """Build steps for a timed work interval (e.g. Plank, Tabata, HIIT)."""
    if announce_halfway and duration_seconds >= 10.0:
        half = duration_seconds / 2.0
        return [
            WorkoutStep(
                spoken_text=phrases.go,
                gap_after=half,
                kind="cue",
                target_interval=half if timing_mode == "cadence" else None,
                section=section,
            ),
            WorkoutStep(
                spoken_text=phrases.halfway,
                gap_after=duration_seconds - half,
                kind="cue",
                target_interval=(duration_seconds - half) if timing_mode == "cadence" else None,
                section=section,
            ),
        ]

    return [
        WorkoutStep(
            spoken_text=phrases.go,
            gap_after=duration_seconds,
            kind="cue",
            target_interval=duration_seconds if timing_mode == "cadence" else None,
            section=section,
        )
    ]


def _build_rep_set_steps(
    reps: int,
    *,
    rep_gap: float,
    phrases: PhrasePack,
    announce_halfway: bool,
    timing_mode: TimingMode,
    section: str,
) -> list[WorkoutStep]:
    steps: list[WorkoutStep] = []
    halfway_rep = reps // 2 if (announce_halfway and reps >= 4) else None

    for rep_number in range(1, reps + 1):
        has_next_rep = rep_number < reps
        gap_after = rep_gap if has_next_rep else 0.0
        target = rep_gap if (timing_mode == "cadence" and has_next_rep and rep_gap > 0) else None
        if halfway_rep is not None and rep_number == halfway_rep:
            steps.append(
                WorkoutStep(
                    spoken_text=str(rep_number),
                    gap_after=0.0,
                    kind="rep",
                    section=section,
                )
            )
            steps.append(
                WorkoutStep(
                    spoken_text=phrases.halfway,
                    gap_after=gap_after,
                    kind="cue",
                    target_interval=target,
                    section=section,
                )
            )
        else:
            steps.append(
                WorkoutStep(
                    spoken_text=str(rep_number),
                    gap_after=gap_after,
                    kind="rep",
                    target_interval=target,
                    section=section,
                )
            )
    return steps


def _build_exercise_steps(
    exercise: ExerciseSpec,
    *,
    config: WorkoutConfig,
    phrases: PhrasePack,
    announce_exercise_name: bool,
) -> list[WorkoutStep]:
    steps: list[WorkoutStep] = []
    total_sets = exercise.total_sets()
    rep_counts = exercise.rep_counts()

    if announce_exercise_name:
        steps.append(
            WorkoutStep(
                spoken_text=exercise.name,
                gap_after=0.5,
                kind="exercise",
                section=exercise.name,
            )
        )

    for set_index in range(total_sets):
        set_number = set_index + 1
        set_label = (
            phrases.format_round(set_number)
            if exercise.duration is not None
            else phrases.format_set(set_number)
        )
        section_name = f"{exercise.name} - {set_label}" if announce_exercise_name else set_label
        is_last_set = config.announce_last_set and total_sets >= 2 and set_number == total_sets

        if is_last_set:
            steps.append(
                WorkoutStep(
                    spoken_text=set_label,
                    gap_after=0.3,
                    kind="set",
                    section=section_name,
                )
            )
            steps.append(
                WorkoutStep(
                    spoken_text=phrases.last_set,
                    gap_after=exercise.set_start_gap,
                    kind="cue",
                    section=section_name,
                )
            )
        else:
            steps.append(
                WorkoutStep(
                    spoken_text=set_label,
                    gap_after=exercise.set_start_gap,
                    kind="set",
                    section=section_name,
                )
            )

        if exercise.duration is not None:
            steps.extend(
                build_timed_work_steps(
                    exercise.duration,
                    phrases=phrases,
                    announce_halfway=config.announce_halfway,
                    timing_mode=config.timing_mode,
                    section=section_name,
                )
            )
        elif rep_counts is not None:
            steps.extend(
                _build_rep_set_steps(
                    rep_counts[set_index],
                    rep_gap=exercise.rep_gap,
                    phrases=phrases,
                    announce_halfway=config.announce_halfway,
                    timing_mode=config.timing_mode,
                    section=section_name,
                )
            )

        if set_number < total_sets:
            steps.extend(
                build_rest_steps(
                    exercise.set_gap,
                    announce_rest=config.announce_rest,
                    phrases=phrases,
                    rest_warnings=config.rest_warnings,
                    timing_mode=config.timing_mode,
                    section=f"Rest after {section_name}",
                )
            )

    return steps


def build_workout_plan(config: WorkoutConfig) -> list[WorkoutStep]:
    phrases = get_phrase_pack(config.language, dict(config.phrase_overrides))
    plan: list[WorkoutStep] = []

    if config.countdown > 0:
        countdown_phrases = [phrases.starting_in] + [
            str(number) for number in range(config.countdown, 0, -1)
        ]
        for index, phrase in enumerate(countdown_phrases):
            is_last = index == len(countdown_phrases) - 1
            gap_after = config.countdown_end_gap if is_last else config.countdown_gap
            target = (
                gap_after
                if (config.timing_mode == "cadence" and not is_last and gap_after > 0)
                else None
            )
            plan.append(
                WorkoutStep(
                    spoken_text=phrase,
                    gap_after=gap_after,
                    kind="countdown",
                    target_interval=target,
                    section="Countdown",
                )
            )

    if config.routine is not None:
        multi_exercise = len(config.routine.exercises) > 1
        for ex_index, exercise in enumerate(config.routine.exercises):
            plan.extend(
                _build_exercise_steps(
                    exercise,
                    config=config,
                    phrases=phrases,
                    announce_exercise_name=multi_exercise or exercise.name.lower() != "work",
                )
            )
            if ex_index + 1 < len(config.routine.exercises):
                transition_gap = (
                    exercise.rest_after
                    if exercise.rest_after is not None
                    else config.routine.exercise_gap
                )
                next_exercise = config.routine.exercises[ex_index + 1]
                plan.extend(
                    build_rest_steps(
                        transition_gap,
                        announce_rest=config.announce_rest,
                        phrases=phrases,
                        rest_warnings=config.rest_warnings,
                        timing_mode=config.timing_mode,
                        section=f"Transition to {next_exercise.name}",
                    )
                )
    elif config.duration is not None:
        single_timed = ExerciseSpec(
            name="Work",
            sets=config.sets,
            duration=config.duration,
            set_gap=config.set_gap,
            set_start_gap=config.set_start_gap,
        )
        plan.extend(
            _build_exercise_steps(
                single_timed,
                config=config,
                phrases=phrases,
                announce_exercise_name=False,
            )
        )
    else:
        single_reps = ExerciseSpec(
            name="Workout",
            sets=config.sets,
            reps=config.reps,
            rep_gap=config.rep_gap,
            set_gap=config.set_gap,
            set_start_gap=config.set_start_gap,
        )
        plan.extend(
            _build_exercise_steps(
                single_reps,
                config=config,
                phrases=phrases,
                announce_exercise_name=False,
            )
        )

    plan.append(
        WorkoutStep(
            spoken_text=phrases.workout_complete,
            gap_after=0.0,
            kind="complete",
            section="Complete",
        )
    )
    return plan


def format_workout_plan(config: WorkoutConfig, plan: list[WorkoutStep]) -> str:
    spoken_cues = sum(1 for step in plan if step.spoken_text is not None)
    total_silence = sum(step.gap_after for step in plan)
    estimated = build_estimated_timeline(plan)
    lines = ["Workout Audio Coach plan"]
    if config.title:
        lines.append(f"Title: {config.title}")
    if config.routine is not None:
        lines.append(f"Routine: {config.routine.name} ({len(config.routine.exercises)} exercises)")
    elif config.duration is not None:
        lines.append(f"Intervals: {config.sets} x {config.duration:g}s")
    else:
        lines.append(f"Sets x reps: {config.sets} x {config.reps}")
    lines.extend(
        [
            f"Timing mode: {config.timing_mode}",
            f"Spoken cues: {spoken_cues}",
            f"Programmed silence: {total_silence:g}s",
            f"Estimated duration: {format_duration(estimated.total_seconds)}",
            "",
        ]
    )

    index_width = max(2, len(str(len(plan))))
    for index, step in enumerate(plan, start=1):
        label = step.spoken_text or "[silence]"
        if step.target_interval is not None and step.target_interval > 0:
            lines.append(f"{index:0{index_width}d}. {label} [cadence {step.target_interval:g}s]")
        elif step.gap_after > 0:
            lines.append(f"{index:0{index_width}d}. {label} [gap {step.gap_after:g}s]")
        else:
            lines.append(f"{index:0{index_width}d}. {label}")

    return "\n".join(lines)


def maybe_write_script_preview(config: WorkoutConfig, plan: list[WorkoutStep]) -> str:
    preview_text = format_workout_plan(config, plan)
    if config.preview:
        print(preview_text)
    if config.script_file is not None:
        config.script_file.parent.mkdir(parents=True, exist_ok=True)
        config.script_file.write_text(preview_text + "\n", encoding="utf-8")
    return preview_text
