from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from workout_audio_coach.config import WorkoutConfig, WorkoutStep
from workout_audio_coach.planner import build_workout_plan
from workout_audio_coach.tts import ensure_ffmpeg_available, load_or_generate_segment

if TYPE_CHECKING:
    from pydub import AudioSegment


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


def concatenate_segments(segments: Sequence[AudioSegment]) -> AudioSegment:
    """Concatenate AudioSegments in O(N) time by normalizing and joining raw PCM buffers."""
    from pydub import AudioSegment

    if not segments:
        return AudioSegment.empty()

    reference = next((seg for seg in segments if len(seg) > 0), None)
    if reference is None:
        return AudioSegment.empty()

    frame_rate: int = reference.frame_rate
    channels: int = reference.channels
    sample_width: int = reference.sample_width

    raw_chunks: list[bytes] = []
    for segment in segments:
        if len(segment) == 0:
            continue
        normalized = segment
        if normalized.frame_rate != frame_rate:
            normalized = normalized.set_frame_rate(frame_rate)
        if normalized.channels != channels:
            normalized = normalized.set_channels(channels)
        if normalized.sample_width != sample_width:
            normalized = normalized.set_sample_width(sample_width)
        raw_chunks.append(normalized.raw_data)

    return AudioSegment(
        data=b"".join(raw_chunks),
        sample_width=sample_width,
        frame_rate=frame_rate,
        channels=channels,
    )


def build_workout_audio(
    config: WorkoutConfig,
    *,
    plan: Sequence[WorkoutStep] | None = None,
    segment_loader: SegmentLoader = load_or_generate_segment,
) -> AudioSegment:
    from pydub import AudioSegment

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

    parts: list[AudioSegment] = []
    for step in resolved_plan:
        if step.spoken_text is not None:
            parts.append(rendered_phrases[step.spoken_text])
        if step.gap_after > 0:
            duration_ms = round(step.gap_after * 1000)
            if duration_ms > 0:
                parts.append(AudioSegment.silent(duration=duration_ms))

    return concatenate_segments(parts)


def export_workout_audio(
    audio: AudioSegment,
    output_file: Path,
    output_format: str,
) -> Path:
    if output_format != "wav":
        ensure_ffmpeg_available()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    export_format = "ipod" if output_format == "m4a" else output_format
    audio.export(output_file, format=export_format)
    return output_file
