from __future__ import annotations

from collections.abc import Sequence

from workout_audio_coach.config import (
    TimingMode,
    WorkoutConfig,
    WorkoutStep,
)
from workout_audio_coach.localization import PhrasePack, get_phrase_pack


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

    halfway_rep = config.reps // 2 if (config.announce_halfway and config.reps >= 4) else None

    for set_number in range(1, config.sets + 1):
        section_name = phrases.format_set(set_number)
        is_last_set = config.announce_last_set and config.sets >= 2 and set_number == config.sets

        if is_last_set:
            plan.append(
                WorkoutStep(
                    spoken_text=section_name,
                    gap_after=0.3,
                    kind="set",
                    section=section_name,
                )
            )
            plan.append(
                WorkoutStep(
                    spoken_text=phrases.last_set,
                    gap_after=config.set_start_gap,
                    kind="cue",
                    section=section_name,
                )
            )
        else:
            plan.append(
                WorkoutStep(
                    spoken_text=section_name,
                    gap_after=config.set_start_gap,
                    kind="set",
                    section=section_name,
                )
            )

        for rep_number in range(1, config.reps + 1):
            has_next_rep = rep_number < config.reps
            gap_after = config.rep_gap if has_next_rep else 0.0
            target = (
                config.rep_gap
                if (config.timing_mode == "cadence" and has_next_rep and config.rep_gap > 0)
                else None
            )
            if halfway_rep is not None and rep_number == halfway_rep:
                plan.append(
                    WorkoutStep(
                        spoken_text=str(rep_number),
                        gap_after=0.0,
                        kind="rep",
                        section=section_name,
                    )
                )
                plan.append(
                    WorkoutStep(
                        spoken_text=phrases.halfway,
                        gap_after=gap_after,
                        kind="cue",
                        target_interval=target,
                        section=section_name,
                    )
                )
            else:
                plan.append(
                    WorkoutStep(
                        spoken_text=str(rep_number),
                        gap_after=gap_after,
                        kind="rep",
                        target_interval=target,
                        section=section_name,
                    )
                )

        if set_number < config.sets:
            plan.extend(
                build_rest_steps(
                    config.set_gap,
                    announce_rest=config.announce_rest,
                    phrases=phrases,
                    rest_warnings=config.rest_warnings,
                    timing_mode=config.timing_mode,
                    section=f"Rest after {section_name}",
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
    lines = [
        "Workout Audio Coach plan",
        f"Sets x reps: {config.sets} x {config.reps}",
        f"Timing mode: {config.timing_mode}",
        f"Spoken cues: {spoken_cues}",
        f"Programmed silence: {total_silence:g}s",
        "",
    ]

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
