from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pydub import AudioSegment

from workout_audio_coach.config import WorkoutConfig, WorkoutStep
from workout_audio_coach.planner import build_workout_plan
from workout_audio_coach.tts import load_or_generate_segment


class SegmentLoader(Protocol):
    def __call__(
        self,
        phrase: str,
        language: str,
        cache_dir: Path,
        *,
        use_cache: bool = True,
        attempts: int = 3,
        initial_backoff_seconds: float = 1.0,
    ) -> AudioSegment: ...


def build_workout_audio(
    config: WorkoutConfig,
    *,
    plan: Sequence[WorkoutStep] | None = None,
    segment_loader: SegmentLoader = load_or_generate_segment,
) -> AudioSegment:
    resolved_plan = list(plan) if plan is not None else build_workout_plan(config)
    unique_phrases = list(
        dict.fromkeys(step.spoken_text for step in resolved_plan if step.spoken_text is not None)
    )
    rendered_phrases = {
        phrase: segment_loader(
            phrase,
            config.language,
            config.cache_dir,
            use_cache=config.use_cache,
            attempts=config.tts_attempts,
            initial_backoff_seconds=config.tts_initial_backoff,
        )
        for phrase in unique_phrases
    }

    combined = AudioSegment.empty()
    for step in resolved_plan:
        if step.spoken_text is not None:
            combined += rendered_phrases[step.spoken_text]
        if step.gap_after > 0:
            combined += AudioSegment.silent(duration=int(step.gap_after * 1000))

    return combined
