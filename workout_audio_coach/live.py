from __future__ import annotations

import os
import select
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from workout_audio_coach.config import StepKind, WorkoutConfig, WorkoutStep
from workout_audio_coach.pcm import PCMAudio
from workout_audio_coach.timeline import (
    build_estimated_timeline,
    estimate_spoken_duration,
    format_duration,
)
from workout_audio_coach.tts import create_tts_backend, load_or_generate_segment

AudioPlayer = Callable[[PCMAudio], None]
KeyReader = Callable[[], str | None]


@dataclass(frozen=True)
class LiveCoachResult:
    completed: bool
    steps_completed: int
    steps_skipped: int
    elapsed_seconds: float


def detect_audio_player_command() -> list[str] | None:
    """Return a platform CLI player command prefix for WAV playback, or None if unavailable."""
    if sys.platform == "darwin" and shutil.which("afplay"):
        return ["afplay"]
    for binary, args in (
        ("paplay", []),
        ("aplay", ["-q"]),
        ("ffplay", ["-nodisp", "-autoexit", "-loglevel", "quiet"]),
    ):
        found = shutil.which(binary)
        if found:
            return [found, *args]
    return None


def play_pcm_audio(audio: PCMAudio, *, player_cmd: Sequence[str] | None = None) -> None:
    cmd_prefix = list(player_cmd) if player_cmd is not None else detect_audio_player_command()
    if not cmd_prefix or audio.frame_count == 0:
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        tmp_path = Path(handle.name)
        handle.write(audio.to_wav_bytes())
    try:
        subprocess.run([*cmd_prefix, str(tmp_path)], capture_output=True, check=False)
    finally:
        tmp_path.unlink(missing_ok=True)


def render_progress_bar(fraction: float, *, width: int = 24) -> str:
    clamped = max(0.0, min(1.0, fraction))
    filled = round(clamped * width)
    return f"[{'#' * filled}{'-' * (width - filled)}] {round(clamped * 100):3d}%"


class _TTYKeyPoller:
    """Non-blocking single-key reader for POSIX TTYs; safely no-ops when non-interactive."""

    def __init__(self) -> None:
        self._fd: int | None = None
        self._saved_settings: list[int | list[bytes | int]] | None = None

    def __enter__(self) -> _TTYKeyPoller:
        if os.name == "posix" and sys.stdin.isatty():
            import termios
            import tty

            self._fd = sys.stdin.fileno()
            self._saved_settings = termios.tcgetattr(self._fd)
            tty.setcbreak(self._fd)
        return self

    def __exit__(self, *exc_info: object) -> None:
        if self._fd is not None and self._saved_settings is not None:
            import termios

            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._saved_settings)

    def poll(self) -> str | None:
        if self._fd is None:
            return None
        ready, _, _ = select.select([self._fd], [], [], 0.0)
        if not ready:
            return None
        return os.read(self._fd, 1).decode("utf-8", errors="ignore").lower()


def _prepare_live_clips(
    config: WorkoutConfig,
    plan: Sequence[WorkoutStep],
) -> dict[tuple[str, StepKind], PCMAudio]:
    backend = create_tts_backend(
        config.tts_backend,
        tld=config.tts_tld,
        slow=config.tts_slow,
        voice=config.tts_voice,
    )
    clips: dict[tuple[str, StepKind], PCMAudio] = {}
    for step in plan:
        if step.spoken_text is None:
            continue
        lookup_kind: StepKind = step.kind if backend.name == "tone" else "cue"
        key = (step.spoken_text, lookup_kind)
        if key not in clips:
            seg = load_or_generate_segment(
                step.spoken_text,
                config.language,
                config.cache_dir,
                use_cache=config.use_cache,
                attempts=config.tts_attempts,
                initial_backoff_seconds=config.tts_initial_backoff,
                backend=backend,
                kind=lookup_kind,
            )
            clips[key] = seg.normalize_dbfs(config.target_dbfs) if config.normalize_audio else seg
    return clips


def run_live_coach(
    config: WorkoutConfig,
    plan: Sequence[WorkoutStep],
    *,
    silent: bool = False,
    output_stream: TextIO | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock_fn: Callable[[], float] = time.monotonic,
    key_reader: KeyReader | None = None,
    audio_player: AudioPlayer | None = None,
    tick_seconds: float = 0.1,
) -> LiveCoachResult:
    """Run a workout plan interactively in real time with progress display and controls."""
    stream = output_stream if output_stream is not None else sys.stdout
    estimated = build_estimated_timeline(plan)
    total_steps = len(plan)

    player_cmd = None if (silent or audio_player is not None) else detect_audio_player_command()
    can_play_audio = not silent and (audio_player is not None or player_cmd is not None)
    clips: dict[tuple[str, StepKind], PCMAudio] = (
        _prepare_live_clips(config, plan) if can_play_audio else {}
    )
    use_tone_kind = config.tts_backend == "tone"

    stream.write(
        f"Workout Audio Coach LIVE  (est. {format_duration(estimated.total_seconds)})\n"
        "Controls: [Space] Pause/Resume  [N] Skip step  [Q] Quit\n\n"
    )
    stream.flush()

    started_at = clock_fn()
    steps_completed = 0
    steps_skipped = 0
    aborted = False

    def _run_loop(poll_key: KeyReader) -> None:
        nonlocal steps_completed, steps_skipped, aborted
        for idx, step in enumerate(plan, start=1):
            label = step.spoken_text or "[silence]"
            section = step.section or "Workout"
            progress = render_progress_bar((idx - 1) / max(1, total_steps))
            stream.write(f"{progress}  [{section}] {label}\n")
            stream.flush()

            spoken_seconds = 0.0
            if step.spoken_text is not None:
                if can_play_audio:
                    lookup_kind: StepKind = step.kind if use_tone_kind else "cue"
                    clip = clips.get((step.spoken_text, lookup_kind))
                    if clip is not None:
                        spoken_seconds = clip.duration_seconds
                        if audio_player is not None:
                            audio_player(clip)
                        else:
                            play_pcm_audio(clip, player_cmd=player_cmd)
                else:
                    spoken_seconds = estimate_spoken_duration(step.spoken_text)

            if step.target_interval is not None and step.target_interval > 0:
                wait_remaining = max(0.0, step.target_interval - spoken_seconds)
            else:
                wait_remaining = max(0.0, step.gap_after)

            paused = False
            skipped = False
            while wait_remaining > 0 or paused:
                key = poll_key()
                if key == "q":
                    aborted = True
                    return
                if key == " ":
                    paused = not paused
                    stream.write("  [PAUSED]\n" if paused else "  [RESUMED]\n")
                    stream.flush()
                elif key == "n":
                    skipped = True
                    break

                if paused:
                    sleep_fn(tick_seconds)
                    continue

                chunk = min(tick_seconds, wait_remaining)
                if chunk > 0:
                    sleep_fn(chunk)
                    wait_remaining -= chunk

            if skipped:
                steps_skipped += 1
            else:
                steps_completed += 1

    if key_reader is not None:
        _run_loop(key_reader)
    else:
        with _TTYKeyPoller() as poller:
            _run_loop(poller.poll)

    elapsed = max(0.0, clock_fn() - started_at)
    if aborted:
        stream.write(f"\nWorkout stopped after {format_duration(elapsed)}.\n")
    else:
        stream.write(
            f"\n{render_progress_bar(1.0)}  Workout finished in {format_duration(elapsed)}!\n"
        )
    stream.flush()

    return LiveCoachResult(
        completed=not aborted,
        steps_completed=steps_completed,
        steps_skipped=steps_skipped,
        elapsed_seconds=round(elapsed, 3),
    )
