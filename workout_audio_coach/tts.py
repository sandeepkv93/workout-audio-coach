from __future__ import annotations

import hashlib
import logging
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Protocol

from gtts import gTTS
from pydub import AudioSegment

LOGGER = logging.getLogger(__name__)


class TTSWriter(Protocol):
    def write_to_fp(self, fp: BinaryIO) -> None: ...


class TTSFactory(Protocol):
    def __call__(self, *, text: str, lang: str) -> TTSWriter: ...


AudioDecoder = Callable[[bytes], AudioSegment]


def phrase_cache_path(cache_dir: Path, phrase: str, language: str) -> Path:
    digest = hashlib.sha256(f"{language}\0{phrase}".encode()).hexdigest()
    return cache_dir / f"{digest}.mp3"


def audio_segment_from_mp3_bytes(audio_bytes: bytes) -> AudioSegment:
    return AudioSegment.from_file(BytesIO(audio_bytes), format="mp3")


def synthesize_phrase(
    phrase: str,
    language: str,
    *,
    attempts: int = 3,
    initial_backoff_seconds: float = 1.0,
    tts_factory: TTSFactory = gTTS,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bytes:
    delay = initial_backoff_seconds
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            buffer = BytesIO()
            tts_factory(text=phrase, lang=language).write_to_fp(buffer)
            return buffer.getvalue()
        except Exception as exc:  # pragma: no cover - network/library failure path
            last_error = exc
            if attempt == attempts:
                break
            LOGGER.warning(
                "Speech synthesis failed for %r on attempt %s/%s; retrying in %.1fs",
                phrase,
                attempt,
                attempts,
                delay,
            )
            sleep_fn(delay)
            delay *= 2

    raise RuntimeError(f"Unable to synthesize speech for {phrase!r}") from last_error


def load_or_generate_segment(
    phrase: str,
    language: str,
    cache_dir: Path,
    *,
    use_cache: bool = True,
    attempts: int = 3,
    initial_backoff_seconds: float = 1.0,
    tts_factory: TTSFactory = gTTS,
    sleep_fn: Callable[[float], None] = time.sleep,
    audio_decoder: AudioDecoder = audio_segment_from_mp3_bytes,
) -> AudioSegment:
    cache_path = phrase_cache_path(cache_dir, phrase, language)
    if use_cache and cache_path.exists():
        LOGGER.debug("Loaded cached speech for %r from %s", phrase, cache_path)
        return audio_decoder(cache_path.read_bytes())

    audio_bytes = synthesize_phrase(
        phrase,
        language,
        attempts=attempts,
        initial_backoff_seconds=initial_backoff_seconds,
        tts_factory=tts_factory,
        sleep_fn=sleep_fn,
    )
    if use_cache:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(audio_bytes)
        LOGGER.debug("Cached speech for %r at %s", phrase, cache_path)
    return audio_decoder(audio_bytes)
