from __future__ import annotations

import math
import struct
import wave
from collections.abc import Sequence
from io import BytesIO

from workout_audio_coach.config import StepKind
from workout_audio_coach.pcm import (
    DEFAULT_SAMPLE_RATE as DEFAULT_SAMPLE_RATE,
)
from workout_audio_coach.pcm import (
    MAX_INT16,
    PCMAudio,
)

CUE_PATTERNS: dict[StepKind, tuple[tuple[float, float], ...]] = {
    "countdown": ((880.0, 0.09),),
    "set": ((523.25, 0.09), (0.0, 0.03), (783.99, 0.14)),
    "exercise": ((523.25, 0.09), (0.0, 0.03), (783.99, 0.14)),
    "rep": ((660.0, 0.07),),
    "rest": ((587.33, 0.10), (0.0, 0.03), (440.0, 0.16)),
    "cue": ((740.0, 0.09),),
    "complete": (
        (523.25, 0.09),
        (0.0, 0.03),
        (659.25, 0.09),
        (0.0, 0.03),
        (783.99, 0.18),
    ),
    "silence": (),
}


def synthesize_tone_wav(
    notes: Sequence[tuple[float, float]],
    *,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    volume: float = 0.45,
    fade_seconds: float = 0.008,
) -> bytes:
    """Synthesize a sequence of (frequency_hz, duration_seconds) pairs into 16-bit mono WAV."""
    if not 0.0 <= volume <= 1.0:
        raise ValueError("volume must be between 0.0 and 1.0")

    samples: list[int] = []
    amplitude = MAX_INT16 * volume

    for frequency_hz, duration_seconds in notes:
        if duration_seconds <= 0:
            continue
        total_frames = max(1, round(sample_rate * duration_seconds))
        if frequency_hz <= 0:
            samples.extend([0] * total_frames)
            continue

        fade_frames = min(total_frames // 2, max(1, round(sample_rate * fade_seconds)))
        angular_step = 2.0 * math.pi * frequency_hz / sample_rate
        for frame in range(total_frames):
            envelope = 1.0
            if frame < fade_frames:
                envelope = frame / fade_frames
            elif frame >= total_frames - fade_frames:
                envelope = (total_frames - 1 - frame) / fade_frames
            sample = round(amplitude * envelope * math.sin(angular_step * frame))
            samples.append(max(-MAX_INT16, min(MAX_INT16, sample)))

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        if samples:
            wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))
    return buffer.getvalue()


def cue_tone_wav_bytes(kind: StepKind, *, sample_rate: int = DEFAULT_SAMPLE_RATE) -> bytes:
    pattern = CUE_PATTERNS.get(kind, CUE_PATTERNS["cue"])
    return synthesize_tone_wav(pattern, sample_rate=sample_rate)


def wav_bytes_to_segment(wav_bytes: bytes) -> PCMAudio:
    return PCMAudio.from_wav_bytes(wav_bytes)
