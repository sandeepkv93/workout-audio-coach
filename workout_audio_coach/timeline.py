from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from workout_audio_coach.config import StepKind, WorkoutStep

SUPPORTED_TIMELINE_FORMATS: tuple[str, ...] = ("vtt", "srt", "lrc", "json")


@dataclass(frozen=True)
class TimelineEntry:
    index: int
    start_seconds: float
    end_seconds: float
    spoken_text: str | None
    kind: StepKind
    section: str | None


@dataclass(frozen=True)
class ChapterMarker:
    title: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class WorkoutTimeline:
    entries: tuple[TimelineEntry, ...]
    chapters: tuple[ChapterMarker, ...]
    total_seconds: float
    is_estimated: bool


def estimate_spoken_duration(text: str) -> float:
    """Estimate spoken audio clip duration in seconds for preview calculations."""
    words = text.split()
    if not words:
        return 0.0
    if len(words) == 1 and len(words[0]) <= 3:
        return 0.45
    return round(0.35 + 0.32 * len(words), 3)


def format_duration(seconds: float) -> str:
    total_whole = max(0, round(seconds))
    hours, remainder = divmod(total_whole, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def build_chapters(entries: Sequence[TimelineEntry]) -> tuple[ChapterMarker, ...]:
    chapters: list[ChapterMarker] = []
    current_title: str | None = None
    current_start: float = 0.0
    current_end: float = 0.0

    for entry in entries:
        title = entry.section or entry.spoken_text or "Workout"
        if current_title is None:
            current_title = title
            current_start = entry.start_seconds
            current_end = entry.end_seconds
        elif title == current_title:
            current_end = entry.end_seconds
        else:
            chapters.append(
                ChapterMarker(
                    title=current_title,
                    start_seconds=round(current_start, 3),
                    end_seconds=round(current_end, 3),
                )
            )
            current_title = title
            current_start = entry.start_seconds
            current_end = entry.end_seconds

    if current_title is not None:
        chapters.append(
            ChapterMarker(
                title=current_title,
                start_seconds=round(current_start, 3),
                end_seconds=round(current_end, 3),
            )
        )

    return tuple(chapters)


def build_estimated_timeline(plan: Sequence[WorkoutStep]) -> WorkoutTimeline:
    entries: list[TimelineEntry] = []
    cursor = 0.0
    for index, step in enumerate(plan, start=1):
        start = cursor
        spoken_duration = (
            estimate_spoken_duration(step.spoken_text) if step.spoken_text is not None else 0.0
        )
        if step.target_interval is not None and step.target_interval > 0:
            step_duration = max(spoken_duration, step.target_interval)
        else:
            step_duration = spoken_duration + max(0.0, step.gap_after)
        cursor += step_duration
        entries.append(
            TimelineEntry(
                index=index,
                start_seconds=round(start, 3),
                end_seconds=round(cursor, 3),
                spoken_text=step.spoken_text,
                kind=step.kind,
                section=step.section,
            )
        )

    return WorkoutTimeline(
        entries=tuple(entries),
        chapters=build_chapters(entries),
        total_seconds=round(cursor, 3),
        is_estimated=True,
    )


def _format_vtt_timestamp(seconds: float) -> str:
    total_ms = max(0, round(seconds * 1000))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def _format_srt_timestamp(seconds: float) -> str:
    return _format_vtt_timestamp(seconds).replace(".", ",")


def _format_lrc_timestamp(seconds: float) -> str:
    total_cs = max(0, round(seconds * 100))
    minutes, rem = divmod(total_cs, 6000)
    secs, centis = divmod(rem, 100)
    return f"[{minutes:02d}:{secs:02d}.{centis:02d}]"


def format_timeline_vtt(timeline: WorkoutTimeline) -> str:
    lines = ["WEBVTT", ""]
    for entry in timeline.entries:
        if entry.spoken_text is None:
            continue
        start = _format_vtt_timestamp(entry.start_seconds)
        end = _format_vtt_timestamp(max(entry.end_seconds, entry.start_seconds + 0.001))
        lines.append(f"{start} --> {end}")
        lines.append(entry.spoken_text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_timeline_srt(timeline: WorkoutTimeline) -> str:
    lines: list[str] = []
    cue_num = 0
    for entry in timeline.entries:
        if entry.spoken_text is None:
            continue
        cue_num += 1
        start = _format_srt_timestamp(entry.start_seconds)
        end = _format_srt_timestamp(max(entry.end_seconds, entry.start_seconds + 0.001))
        lines.append(str(cue_num))
        lines.append(f"{start} --> {end}")
        lines.append(entry.spoken_text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def format_timeline_lrc(timeline: WorkoutTimeline) -> str:
    lines: list[str] = []
    for entry in timeline.entries:
        if entry.spoken_text is None:
            continue
        lines.append(f"{_format_lrc_timestamp(entry.start_seconds)}{entry.spoken_text}")
    return "\n".join(lines) + ("\n" if lines else "")


def format_timeline_json(timeline: WorkoutTimeline) -> str:
    payload = {
        "total_seconds": timeline.total_seconds,
        "formatted_duration": format_duration(timeline.total_seconds),
        "is_estimated": timeline.is_estimated,
        "chapters": [
            {
                "title": chapter.title,
                "start_seconds": chapter.start_seconds,
                "end_seconds": chapter.end_seconds,
            }
            for chapter in timeline.chapters
        ],
        "entries": [
            {
                "index": entry.index,
                "start_seconds": entry.start_seconds,
                "end_seconds": entry.end_seconds,
                "spoken_text": entry.spoken_text,
                "kind": entry.kind,
                "section": entry.section,
            }
            for entry in timeline.entries
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def export_timeline(timeline: WorkoutTimeline, output_path: Path) -> Path:
    suffix = output_path.suffix.lower().lstrip(".")
    if suffix == "vtt":
        content = format_timeline_vtt(timeline)
    elif suffix == "srt":
        content = format_timeline_srt(timeline)
    elif suffix == "lrc":
        content = format_timeline_lrc(timeline)
    elif suffix == "json":
        content = format_timeline_json(timeline)
    else:
        supported = ", ".join(f".{fmt}" for fmt in SUPPORTED_TIMELINE_FORMATS)
        raise ValueError(
            f"unsupported timestamps file extension '.{suffix}'; supported formats: {supported}"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return output_path
