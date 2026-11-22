from __future__ import annotations

from workout_audio_coach.config import (
    DEFAULT_COUNTDOWN_GAP_SECONDS,
    WorkoutConfig,
    WorkoutStep,
)


def build_workout_plan(config: WorkoutConfig) -> list[WorkoutStep]:
    plan: list[WorkoutStep] = []

    if config.countdown > 0:
        countdown_phrases = ["Starting in"] + [
            str(number) for number in range(config.countdown, 0, -1)
        ]
        for index, phrase in enumerate(countdown_phrases):
            gap_after = DEFAULT_COUNTDOWN_GAP_SECONDS
            if index == len(countdown_phrases) - 1:
                gap_after = 0.0
            plan.append(WorkoutStep(spoken_text=phrase, gap_after=gap_after))

    for set_number in range(1, config.sets + 1):
        plan.append(WorkoutStep(spoken_text=f"Set {set_number}", gap_after=config.set_start_gap))
        for rep_number in range(1, config.reps + 1):
            gap_after = config.rep_gap if rep_number < config.reps else 0.0
            plan.append(WorkoutStep(spoken_text=str(rep_number), gap_after=gap_after))

        if set_number < config.sets:
            if config.announce_rest:
                plan.append(WorkoutStep(spoken_text="Rest", gap_after=config.set_gap))
            elif config.set_gap > 0:
                plan.append(WorkoutStep(spoken_text=None, gap_after=config.set_gap))

    plan.append(WorkoutStep(spoken_text="Workout complete"))
    return plan


def format_workout_plan(config: WorkoutConfig, plan: list[WorkoutStep]) -> str:
    spoken_cues = sum(1 for step in plan if step.spoken_text is not None)
    total_silence = sum(step.gap_after for step in plan)
    lines = [
        "Workout Audio Coach plan",
        f"Sets x reps: {config.sets} x {config.reps}",
        f"Spoken cues: {spoken_cues}",
        f"Programmed silence: {total_silence:g}s",
        "",
    ]

    index_width = max(2, len(str(len(plan))))
    for index, step in enumerate(plan, start=1):
        label = step.spoken_text or "[silence]"
        if step.gap_after > 0:
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
