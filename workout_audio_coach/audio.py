from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Protocol

from workout_audio_coach.config import StepKind, WorkoutConfig, WorkoutStep
from workout_audio_coach.pcm import (
    PCMAudio,
    concatenate_pcm,
    ensure_ffmpeg_available,
    mix_background_music,
)
from workout_audio_coach.planner import build_workout_plan
from workout_audio_coach.timeline import TimelineEntry, WorkoutTimeline, build_chapters
from workout_audio_coach.tones import cue_tone_wav_bytes, wav_bytes_to_segment
from workout_audio_coach.tts import (
    TTSBackend,
    create_tts_backend,
    load_or_generate_segment,
)

BEEP_TRIGGER_KINDS: frozenset[StepKind] = frozenset(
    {"countdown", "set", "exercise", "rest", "complete"}
)


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
    ) -> PCMAudio: ...


def concatenate_segments(segments: Sequence[PCMAudio]) -> PCMAudio:
    """Concatenate PCMAudio segments in O(N) time by normalizing and joining raw PCM buffers."""
    return concatenate_pcm(segments)


def _uses_custom_backend_settings(config: WorkoutConfig) -> bool:
    return (
        config.tts_backend != "gtts"
        or config.tts_tld != "com"
        or config.tts_slow
        or config.tts_voice is not None
    )


def _maybe_normalize(segment: PCMAudio, config: WorkoutConfig) -> PCMAudio:
    if config.normalize_audio:
        return segment.normalize_dbfs(config.target_dbfs)
    return segment


def build_workout_audio_with_timeline(
    config: WorkoutConfig,
    *,
    plan: Sequence[WorkoutStep] | None = None,
    segment_loader: SegmentLoader | None = None,
    backend: TTSBackend | None = None,
) -> tuple[PCMAudio, WorkoutTimeline]:
    resolved_plan = list(plan) if plan is not None else build_workout_plan(config)
    use_explicit_loader = (
        segment_loader is not None and backend is None and not _uses_custom_backend_settings(config)
    )
    resolved_backend = (
        backend
        if backend is not None
        else create_tts_backend(
            config.tts_backend,
            tld=config.tts_tld,
            slow=config.tts_slow,
            voice=config.tts_voice,
        )
    )

    rendered_phrases: dict[tuple[str, StepKind], PCMAudio] = {}
    if use_explicit_loader and segment_loader is not None:
        unique_texts = list(
            dict.fromkeys(
                step.spoken_text for step in resolved_plan if step.spoken_text is not None
            )
        )
        by_text = {
            phrase: _maybe_normalize(
                segment_loader(
                    phrase,
                    config.language,
                    config.cache_dir,
                    use_cache=config.use_cache,
                    attempts=config.tts_attempts,
                    initial_backoff_seconds=config.tts_initial_backoff,
                ),
                config,
            )
            for phrase in unique_texts
        }
        for step in resolved_plan:
            if step.spoken_text is not None:
                rendered_phrases[(step.spoken_text, step.kind)] = by_text[step.spoken_text]
    else:
        cache_keys: list[tuple[str, StepKind]] = []
        seen_keys: set[tuple[str, StepKind]] = set()
        for step in resolved_plan:
            if step.spoken_text is None:
                continue
            key = (step.spoken_text, step.kind if resolved_backend.name == "tone" else "cue")
            if key not in seen_keys:
                seen_keys.add(key)
                cache_keys.append(key)

        def _fetch_one(item: tuple[str, StepKind]) -> tuple[tuple[str, StepKind], PCMAudio]:
            phrase, kind = item
            seg = load_or_generate_segment(
                phrase,
                config.language,
                config.cache_dir,
                use_cache=config.use_cache,
                attempts=config.tts_attempts,
                initial_backoff_seconds=config.tts_initial_backoff,
                backend=resolved_backend,
                kind=kind,
            )
            return item, _maybe_normalize(seg, config)

        loaded_by_key: dict[tuple[str, StepKind], PCMAudio] = {}
        worker_count = max(1, min(config.tts_workers, len(cache_keys))) if cache_keys else 1
        if worker_count > 1:
            with ThreadPoolExecutor(max_workers=worker_count) as pool:
                for key, seg in pool.map(_fetch_one, cache_keys):
                    loaded_by_key[key] = seg
        else:
            for item in cache_keys:
                key, seg = _fetch_one(item)
                loaded_by_key[key] = seg

        for step in resolved_plan:
            if step.spoken_text is not None:
                lookup_kind: StepKind = step.kind if resolved_backend.name == "tone" else "cue"
                rendered_phrases[(step.spoken_text, step.kind)] = loaded_by_key[
                    (step.spoken_text, lookup_kind)
                ]

    beep_cache: dict[StepKind, PCMAudio] = {}
    parts: list[PCMAudio] = []
    entries: list[TimelineEntry] = []
    speech_ranges_ms: list[tuple[int, int]] = []
    cursor_ms = 0

    for index, step in enumerate(resolved_plan, start=1):
        step_start_ms = cursor_ms
        spoken_ms = 0
        if config.beep_cues and resolved_backend.name != "tone" and step.kind in BEEP_TRIGGER_KINDS:
            if step.kind not in beep_cache:
                beep_cache[step.kind] = _maybe_normalize(
                    wav_bytes_to_segment(cue_tone_wav_bytes(step.kind)),
                    config,
                )
            beep_seg = beep_cache[step.kind]
            if len(beep_seg) > 0:
                parts.append(beep_seg)
                spoken_ms += len(beep_seg)

        if step.spoken_text is not None:
            segment = rendered_phrases[(step.spoken_text, step.kind)]
            parts.append(segment)
            spoken_ms += len(segment)

        if spoken_ms > 0:
            speech_ranges_ms.append((step_start_ms, step_start_ms + spoken_ms))

        if step.target_interval is not None and step.target_interval > 0:
            duration_ms = max(0, round(step.target_interval * 1000) - spoken_ms)
        elif step.gap_after > 0:
            duration_ms = round(step.gap_after * 1000)
        else:
            duration_ms = 0

        if duration_ms > 0:
            parts.append(PCMAudio.silent(duration=duration_ms))

        cursor_ms += spoken_ms + duration_ms
        entries.append(
            TimelineEntry(
                index=index,
                start_seconds=round(step_start_ms / 1000.0, 3),
                end_seconds=round(cursor_ms / 1000.0, 3),
                spoken_text=step.spoken_text,
                kind=step.kind,
                section=step.section,
            )
        )

    combined = concatenate_segments(parts)
    if config.music_file is not None and combined.frame_count > 0:
        music = PCMAudio.from_file(config.music_file)
        combined = mix_background_music(
            combined,
            music,
            speech_ranges_ms=speech_ranges_ms,
            music_gain_db=config.music_gain_db,
            duck_db=config.duck_db,
        )

    timeline = WorkoutTimeline(
        entries=tuple(entries),
        chapters=build_chapters(entries),
        total_seconds=round(cursor_ms / 1000.0, 3),
        is_estimated=False,
    )
    return combined, timeline


def build_workout_audio(
    config: WorkoutConfig,
    *,
    plan: Sequence[WorkoutStep] | None = None,
    segment_loader: SegmentLoader | None = None,
    backend: TTSBackend | None = None,
) -> PCMAudio:
    combined, _ = build_workout_audio_with_timeline(
        config,
        plan=plan,
        segment_loader=segment_loader,
        backend=backend,
    )
    return combined


def build_audio_metadata_tags(config: WorkoutConfig) -> dict[str, str]:
    if config.title:
        title = config.title
    elif config.routine is not None:
        title = config.routine.name
    elif config.duration is not None:
        title = f"{config.sets}x{config.duration:g}s Interval Workout"
    else:
        title = f"{config.sets}x{config.reps} Workout"
    return {
        "title": title,
        "artist": "Workout Audio Coach",
        "album": config.routine.name if config.routine is not None else "Workout Audio Coach",
        "genre": "Workout",
    }


def export_workout_audio(
    audio: PCMAudio,
    output_file: Path,
    output_format: str,
    *,
    tags: Mapping[str, str] | None = None,
) -> Path:
    if output_format != "wav":
        ensure_ffmpeg_available()
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if tags and output_format != "wav":
        audio.export(output_file, format=output_format, tags=dict(tags))
    else:
        audio.export(output_file, format=output_format)
    return output_file
