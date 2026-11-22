from __future__ import annotations

import hashlib
import logging
import os
import shutil
import tempfile
import time
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO, Protocol

if TYPE_CHECKING:
    from pydub import AudioSegment

LOGGER = logging.getLogger(__name__)


class TTSWriter(Protocol):
    def write_to_fp(self, fp: BinaryIO) -> None: ...


class TTSFactory(Protocol):
    def __call__(self, *, text: str, lang: str) -> TTSWriter: ...


AudioDecoder = Callable[[bytes], "AudioSegment"]


def default_tts_factory(*, text: str, lang: str) -> TTSWriter:
    from gtts import gTTS

    writer: TTSWriter = gTTS(text=text, lang=lang)
    return writer


def ensure_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None and shutil.which("avconv") is None:
        raise RuntimeError(
            "ffmpeg is required to decode or export compressed audio formats, "
            "but neither 'ffmpeg' nor 'avconv' was found on PATH. "
            "Install ffmpeg (e.g. 'brew install ffmpeg' or 'sudo apt-get install ffmpeg')."
        )


def phrase_cache_path(cache_dir: Path, phrase: str, language: str) -> Path:
    digest = hashlib.sha256(f"{language}\0{phrase}".encode()).hexdigest()
    return cache_dir / f"{digest}.mp3"


def _write_bytes_atomically(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            dir=target.parent,
            prefix=f".{target.stem}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(data)
        os.replace(tmp_path, target)
    except Exception:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise


def audio_segment_from_mp3_bytes(audio_bytes: bytes) -> AudioSegment:
    ensure_ffmpeg_available()
    from pydub import AudioSegment

    return AudioSegment.from_file(BytesIO(audio_bytes), format="mp3")


def synthesize_phrase(
    phrase: str,
    language: str,
    *,
    attempts: int = 3,
    initial_backoff_seconds: float = 1.0,
    tts_factory: TTSFactory | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bytes:
    factory = tts_factory if tts_factory is not None else default_tts_factory
    delay = initial_backoff_seconds
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            buffer = BytesIO()
            factory(text=phrase, lang=language).write_to_fp(buffer)
            payload = buffer.getvalue()
            if not payload:
                raise RuntimeError("synthesized audio payload was empty")
            return payload
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
    tts_factory: TTSFactory | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    audio_decoder: AudioDecoder = audio_segment_from_mp3_bytes,
) -> AudioSegment:
    cache_path = phrase_cache_path(cache_dir, phrase, language)
    if use_cache and cache_path.exists():
        try:
            cached_bytes = cache_path.read_bytes()
            if not cached_bytes:
                raise ValueError("cached audio file is empty")
            segment = audio_decoder(cached_bytes)
            LOGGER.debug("Loaded cached speech for %r from %s", phrase, cache_path)
            return segment
        except Exception as exc:
            LOGGER.warning(
                "Cached speech for %r at %s could not be decoded (%s); regenerating",
                phrase,
                cache_path,
                exc,
            )
            cache_path.unlink(missing_ok=True)

    audio_bytes = synthesize_phrase(
        phrase,
        language,
        attempts=attempts,
        initial_backoff_seconds=initial_backoff_seconds,
        tts_factory=tts_factory,
        sleep_fn=sleep_fn,
    )
    segment = audio_decoder(audio_bytes)
    if use_cache:
        _write_bytes_atomically(cache_path, audio_bytes)
        LOGGER.debug("Cached speech for %r at %s", phrase, cache_path)
    return segment
