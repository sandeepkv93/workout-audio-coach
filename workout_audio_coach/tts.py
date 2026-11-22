from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Protocol

from workout_audio_coach.config import StepKind, TTSBackendName
from workout_audio_coach.pcm import PCMAudio
from workout_audio_coach.tones import cue_tone_wav_bytes, wav_bytes_to_segment

LOGGER = logging.getLogger(__name__)

CACHE_EXTENSIONS: frozenset[str] = frozenset({".mp3", ".wav"})

EDGE_DEFAULT_VOICES: dict[str, str] = {
    "en": "en-US-GuyNeural",
    "es": "es-ES-AlvaroNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-ConradNeural",
    "it": "it-IT-DiegoNeural",
    "pt": "pt-BR-AntonioNeural",
    "hi": "hi-IN-MadhurNeural",
    "ja": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural",
    "zh": "zh-CN-YunxiNeural",
}


class TTSWriter(Protocol):
    def write_to_fp(self, fp: BinaryIO) -> None: ...


class TTSFactory(Protocol):
    def __call__(self, *, text: str, lang: str) -> TTSWriter: ...


class TTSBackend(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def file_extension(self) -> str: ...

    def cache_namespace(self) -> str: ...

    def synthesize(self, phrase: str, language: str, *, kind: StepKind = "cue") -> bytes: ...


@dataclass(frozen=True)
class CacheStats:
    cache_dir: Path
    file_count: int
    total_bytes: int


AudioDecoder = Callable[[bytes], PCMAudio]


def default_tts_factory(*, text: str, lang: str) -> TTSWriter:
    from gtts import gTTS

    writer: TTSWriter = gTTS(text=text, lang=lang)
    return writer


def phrase_cache_path(
    cache_dir: Path,
    phrase: str,
    language: str,
    *,
    namespace: str = "",
    extension: str = "mp3",
) -> Path:
    key = f"{namespace}\0{language}\0{phrase}" if namespace else f"{language}\0{phrase}"
    digest = hashlib.sha256(key.encode()).hexdigest()
    return cache_dir / f"{digest}.{extension}"


def get_cache_stats(cache_dir: Path) -> CacheStats:
    if not cache_dir.exists():
        return CacheStats(cache_dir=cache_dir, file_count=0, total_bytes=0)
    count = 0
    total = 0
    for entry in cache_dir.iterdir():
        if entry.is_file() and entry.suffix.lower() in CACHE_EXTENSIONS:
            count += 1
            total += entry.stat().st_size
    return CacheStats(cache_dir=cache_dir, file_count=count, total_bytes=total)


def clear_cache(cache_dir: Path) -> CacheStats:
    stats = get_cache_stats(cache_dir)
    if cache_dir.exists():
        for entry in cache_dir.iterdir():
            if entry.is_file() and (
                entry.suffix.lower() in CACHE_EXTENSIONS or entry.suffix.lower() == ".tmp"
            ):
                entry.unlink(missing_ok=True)
    return stats


def format_cache_stats(stats: CacheStats) -> str:
    size_kb = stats.total_bytes / 1024.0
    size_str = f"{size_kb / 1024.0:.2f} MB" if size_kb >= 1024.0 else f"{size_kb:.1f} KB"
    return f"Cache directory: {stats.cache_dir}\nCached clips: {stats.file_count} ({size_str})"


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


def audio_segment_from_mp3_bytes(audio_bytes: bytes) -> PCMAudio:
    return PCMAudio.from_compressed_bytes(audio_bytes, "mp3")


def decode_audio_bytes(audio_bytes: bytes, file_extension: str) -> PCMAudio:
    if file_extension == "wav":
        return wav_bytes_to_segment(audio_bytes)
    return audio_segment_from_mp3_bytes(audio_bytes)


class GTTSBackend:
    """Google Text-to-Speech backend (online, outputs MP3)."""

    def __init__(
        self,
        *,
        tld: str = "com",
        slow: bool = False,
        tts_factory: TTSFactory | None = None,
    ) -> None:
        self.tld = tld
        self.slow = slow
        self.tts_factory = tts_factory

    @property
    def name(self) -> str:
        return "gtts"

    @property
    def file_extension(self) -> str:
        return "mp3"

    def cache_namespace(self) -> str:
        if self.tld == "com" and not self.slow:
            return ""
        return f"gtts:tld={self.tld}:slow={int(self.slow)}"

    def synthesize(self, phrase: str, language: str, *, kind: StepKind = "cue") -> bytes:
        del kind
        buffer = BytesIO()
        if self.tts_factory is not None:
            self.tts_factory(text=phrase, lang=language).write_to_fp(buffer)
        else:
            from gtts import gTTS

            gTTS(text=phrase, lang=language, tld=self.tld, slow=self.slow).write_to_fp(buffer)
        return buffer.getvalue()


class EdgeTTSBackend:
    """Neural TTS backend powered by optional `edge-tts` package or CLI."""

    def __init__(self, *, voice: str | None = None, executable: str | None = None) -> None:
        self.voice = voice
        self.executable = executable

    @property
    def name(self) -> str:
        return "edge"

    @property
    def file_extension(self) -> str:
        return "mp3"

    def resolve_voice(self, language: str) -> str:
        if self.voice:
            return self.voice
        primary = language.strip().lower().replace("_", "-").split("-", 1)[0]
        return EDGE_DEFAULT_VOICES.get(primary, EDGE_DEFAULT_VOICES["en"])

    def cache_namespace(self) -> str:
        return f"edge:voice={self.voice or 'auto'}"

    def synthesize(self, phrase: str, language: str, *, kind: StepKind = "cue") -> bytes:
        del kind
        voice = self.resolve_voice(language)
        if self.executable is None:
            try:
                import edge_tts

                async def _generate() -> bytes:
                    chunks: list[bytes] = []
                    communicator = edge_tts.Communicate(phrase, voice)
                    async for item in communicator.stream():
                        if isinstance(item, dict) and item.get("type") == "audio":
                            data = item.get("data")
                            if isinstance(data, bytes):
                                chunks.append(data)
                    return b"".join(chunks)

                return asyncio.run(_generate())
            except ImportError:
                pass

        binary = self.executable or shutil.which("edge-tts")
        if binary is None:
            raise RuntimeError(
                "edge backend requires the optional 'edge-tts' package or CLI. "
                "Install it with 'uv add edge-tts' or 'pip install edge-tts'."
            )
        with tempfile.TemporaryDirectory() as tmpdir:
            mp3_path = Path(tmpdir) / "clip.mp3"
            cmd = [binary, "--voice", voice, "--text", phrase, "--write-media", str(mp3_path)]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                stderr = result.stderr.strip() or f"exit code {result.returncode}"
                raise RuntimeError(f"edge-tts synthesis failed: {stderr}")
            return mp3_path.read_bytes()


class PiperBackend:
    """Offline neural TTS backend powered by local `piper` CLI and ONNX voice model."""

    def __init__(self, *, model: str | None = None, executable: str | None = None) -> None:
        self.model = model
        self.executable = executable

    @property
    def name(self) -> str:
        return "piper"

    @property
    def file_extension(self) -> str:
        return "wav"

    def cache_namespace(self) -> str:
        return f"piper:model={self.model or ''}"

    def synthesize(self, phrase: str, language: str, *, kind: StepKind = "cue") -> bytes:
        del language, kind
        binary = self.executable or shutil.which("piper")
        if binary is None:
            raise RuntimeError(
                "piper backend requires the 'piper' CLI on PATH. "
                "Install piper-tts (e.g. 'pip install piper-tts') and pass --tts-voice MODEL.onnx."
            )
        if not self.model:
            raise RuntimeError(
                "piper backend requires a voice model path via --tts-voice /path/to/model.onnx."
            )
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "clip.wav"
            cmd = [binary, "--model", self.model, "--output_file", str(wav_path)]
            result = subprocess.run(
                cmd,
                input=phrase + "\n",
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                stderr = result.stderr.strip() or f"exit code {result.returncode}"
                raise RuntimeError(f"piper synthesis failed: {stderr}")
            return wav_path.read_bytes()


class ToneBackend:
    """100% offline synthesized tone/chime backend (no network or ffmpeg needed for WAV)."""

    @property
    def name(self) -> str:
        return "tone"

    @property
    def file_extension(self) -> str:
        return "wav"

    def cache_namespace(self) -> str:
        return "tone:v1"

    def synthesize(self, phrase: str, language: str, *, kind: StepKind = "cue") -> bytes:
        del phrase, language
        return cue_tone_wav_bytes(kind)


class EspeakBackend:
    """Offline TTS backend powered by local espeak-ng / espeak CLI."""

    def __init__(self, *, voice: str | None = None, executable: str | None = None) -> None:
        self.voice = voice
        self.executable = executable

    @property
    def name(self) -> str:
        return "espeak"

    @property
    def file_extension(self) -> str:
        return "wav"

    def cache_namespace(self) -> str:
        return f"espeak:voice={self.voice or ''}"

    def _resolve_executable(self) -> str:
        if self.executable is not None:
            return self.executable
        found = shutil.which("espeak-ng") or shutil.which("espeak")
        if found is None:
            raise RuntimeError(
                "espeak backend requires 'espeak-ng' or 'espeak' on PATH. "
                "Install it (e.g. 'sudo apt-get install espeak-ng' or 'brew install espeak-ng')."
            )
        return found

    def synthesize(self, phrase: str, language: str, *, kind: StepKind = "cue") -> bytes:
        del kind
        binary = self._resolve_executable()
        voice_arg = self.voice or language
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "clip.wav"
            cmd = [binary, "-v", voice_arg, "-w", str(wav_path), phrase]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                stderr = result.stderr.strip() or f"exit code {result.returncode}"
                raise RuntimeError(f"espeak synthesis failed: {stderr}")
            return wav_path.read_bytes()


class MacOSSayBackend:
    """Offline TTS backend powered by the macOS 'say' command."""

    def __init__(self, *, voice: str | None = None, executable: str | None = None) -> None:
        self.voice = voice
        self.executable = executable

    @property
    def name(self) -> str:
        return "say"

    @property
    def file_extension(self) -> str:
        return "wav"

    def cache_namespace(self) -> str:
        return f"say:voice={self.voice or ''}"

    def _resolve_executable(self) -> str:
        if self.executable is not None:
            return self.executable
        found = shutil.which("say")
        if found is None:
            raise RuntimeError(
                "say backend requires the macOS 'say' command on PATH, "
                "which is only available on macOS."
            )
        return found

    def synthesize(self, phrase: str, language: str, *, kind: StepKind = "cue") -> bytes:
        del language, kind
        binary = self._resolve_executable()
        with tempfile.TemporaryDirectory() as tmpdir:
            wav_path = Path(tmpdir) / "clip.wav"
            cmd = [binary, "--file-format=WAVE", "--data-format=LEI16@24000", "-o", str(wav_path)]
            if self.voice:
                cmd.extend(["-v", self.voice])
            cmd.append(phrase)
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                stderr = result.stderr.strip() or f"exit code {result.returncode}"
                raise RuntimeError(f"macOS say synthesis failed: {stderr}")
            return wav_path.read_bytes()


def create_tts_backend(
    backend: TTSBackendName,
    *,
    tld: str = "com",
    slow: bool = False,
    voice: str | None = None,
    tts_factory: TTSFactory | None = None,
) -> TTSBackend:
    if backend == "gtts":
        return GTTSBackend(tld=tld, slow=slow, tts_factory=tts_factory)
    if backend == "edge":
        return EdgeTTSBackend(voice=voice)
    if backend == "piper":
        return PiperBackend(model=voice)
    if backend == "tone":
        return ToneBackend()
    if backend == "espeak":
        return EspeakBackend(voice=voice)
    if backend == "say":
        return MacOSSayBackend(voice=voice)
    raise ValueError(f"unsupported TTS backend: {backend!r}")


def synthesize_phrase(
    phrase: str,
    language: str,
    *,
    attempts: int = 3,
    initial_backoff_seconds: float = 1.0,
    tts_factory: TTSFactory | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    backend: TTSBackend | None = None,
    kind: StepKind = "cue",
) -> bytes:
    resolved_backend: TTSBackend = (
        backend
        if backend is not None
        else GTTSBackend(
            tts_factory=tts_factory if tts_factory is not None else default_tts_factory
        )
    )
    delay = initial_backoff_seconds
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            payload = resolved_backend.synthesize(phrase, language, kind=kind)
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
    audio_decoder: AudioDecoder | None = None,
    backend: TTSBackend | None = None,
    kind: StepKind = "cue",
) -> PCMAudio:
    resolved_backend: TTSBackend = (
        backend
        if backend is not None
        else GTTSBackend(
            tts_factory=tts_factory if tts_factory is not None else default_tts_factory
        )
    )
    extension = resolved_backend.file_extension
    namespace = resolved_backend.cache_namespace()
    cache_phrase = f"{kind}:{phrase}" if resolved_backend.name == "tone" else phrase
    cache_path = phrase_cache_path(
        cache_dir,
        cache_phrase,
        language,
        namespace=namespace,
        extension=extension,
    )

    def _decode(data: bytes) -> PCMAudio:
        if audio_decoder is not None:
            return audio_decoder(data)
        return decode_audio_bytes(data, extension)

    if use_cache and cache_path.exists():
        try:
            cached_bytes = cache_path.read_bytes()
            if not cached_bytes:
                raise ValueError("cached audio file is empty")
            segment = _decode(cached_bytes)
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
        backend=resolved_backend,
        kind=kind,
    )
    segment = _decode(audio_bytes)
    if use_cache:
        _write_bytes_atomically(cache_path, audio_bytes)
        LOGGER.debug("Cached speech for %r at %s", phrase, cache_path)
    return segment
