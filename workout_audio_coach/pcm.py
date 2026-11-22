from __future__ import annotations

import array
import math
import shutil
import struct
import subprocess
import sys
import wave
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

DEFAULT_SAMPLE_RATE: int = 24000
MAX_INT16: int = 32767
MIN_INT16: int = -32768
PCM_SAMPLE_WIDTH: int = 2


def ensure_ffmpeg_available() -> str:
    """Return path to ffmpeg/avconv binary or raise an actionable RuntimeError."""
    binary = shutil.which("ffmpeg") or shutil.which("avconv")
    if binary is None:
        raise RuntimeError(
            "ffmpeg is required to decode or export compressed audio formats, "
            "but neither 'ffmpeg' nor 'avconv' was found on PATH. "
            "Install ffmpeg (e.g. 'brew install ffmpeg' or 'sudo apt-get install ffmpeg')."
        )
    return binary


def _bytes_to_int16_array(raw_data: bytes) -> array.array[int]:
    samples = array.array("h")
    samples.frombytes(raw_data)
    if sys.byteorder != "little":
        samples.byteswap()
    return samples


def _int16_array_to_bytes(samples: array.array[int]) -> bytes:
    if sys.byteorder != "little":
        swapped = array.array("h", samples)
        swapped.byteswap()
        return swapped.tobytes()
    return samples.tobytes()


def _clamp_int16(value: float) -> int:
    rounded = round(value)
    if rounded > MAX_INT16:
        return MAX_INT16
    if rounded < MIN_INT16:
        return MIN_INT16
    return rounded


def _convert_to_16bit_pcm(raw_frames: bytes, sample_width: int) -> bytes:
    if sample_width == 2:
        return raw_frames
    if sample_width == 1:
        # 8-bit WAV PCM is unsigned [0, 255] centered at 128
        out = array.array("h", ((byte - 128) << 8 for byte in raw_frames))
        return _int16_array_to_bytes(out)
    if sample_width == 3:
        # 24-bit signed little-endian -> top 16 bits
        count = len(raw_frames) // 3
        out = array.array("h")
        for idx in range(count):
            offset = idx * 3
            val24 = int.from_bytes(raw_frames[offset : offset + 3], "little", signed=True)
            out.append(val24 >> 8)
        return _int16_array_to_bytes(out)
    if sample_width == 4:
        count = len(raw_frames) // 4
        ints = struct.unpack(f"<{count}i", raw_frames)
        out = array.array("h", (v >> 16 for v in ints))
        return _int16_array_to_bytes(out)
    raise ValueError(f"unsupported WAV sample width: {sample_width} bytes")


@dataclass(frozen=True)
class PCMAudio:
    """Pure-Python 16-bit signed little-endian PCM audio buffer."""

    raw_data: bytes
    frame_rate: int = DEFAULT_SAMPLE_RATE
    channels: int = 1
    sample_width: int = PCM_SAMPLE_WIDTH

    def __post_init__(self) -> None:
        if self.frame_rate <= 0:
            raise ValueError("frame_rate must be positive")
        if self.channels <= 0:
            raise ValueError("channels must be positive")
        if self.sample_width != PCM_SAMPLE_WIDTH:
            raise ValueError("PCMAudio only stores 16-bit (2-byte) PCM samples")
        frame_bytes = self.channels * self.sample_width
        if len(self.raw_data) % frame_bytes != 0:
            raise ValueError("raw_data length must be a multiple of frame size")

    @property
    def frame_count(self) -> int:
        return len(self.raw_data) // (self.channels * self.sample_width)

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.frame_rate

    def __len__(self) -> int:
        """Duration in milliseconds."""
        return round(self.frame_count * 1000 / self.frame_rate)

    @classmethod
    def empty(cls, *, frame_rate: int = DEFAULT_SAMPLE_RATE, channels: int = 1) -> PCMAudio:
        return cls(raw_data=b"", frame_rate=frame_rate, channels=channels)

    @classmethod
    def silent(
        cls,
        duration: int,
        *,
        frame_rate: int = DEFAULT_SAMPLE_RATE,
        channels: int = 1,
    ) -> PCMAudio:
        """Create silent PCM audio of `duration` milliseconds."""
        if duration <= 0:
            return cls.empty(frame_rate=frame_rate, channels=channels)
        frames = round(frame_rate * duration / 1000.0)
        return cls(
            raw_data=b"\x00" * (frames * channels * PCM_SAMPLE_WIDTH),
            frame_rate=frame_rate,
            channels=channels,
        )

    @classmethod
    def from_wav_bytes(cls, wav_bytes: bytes) -> PCMAudio:
        with wave.open(BytesIO(wav_bytes), "rb") as handle:
            channels = handle.getnchannels()
            sample_width = handle.getsampwidth()
            frame_rate = handle.getframerate()
            raw_frames = handle.readframes(handle.getnframes())
        pcm_16 = _convert_to_16bit_pcm(raw_frames, sample_width)
        return cls(raw_data=pcm_16, frame_rate=frame_rate, channels=channels)

    @classmethod
    def from_compressed_bytes(cls, data: bytes, audio_format: str) -> PCMAudio:
        ffmpeg_bin = ensure_ffmpeg_available()
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            audio_format,
            "-i",
            "pipe:0",
            "-f",
            "wav",
            "-acodec",
            "pcm_s16le",
            "pipe:1",
        ]
        result = subprocess.run(cmd, input=data, capture_output=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg failed to decode {audio_format} audio: {stderr}")
        return cls.from_wav_bytes(result.stdout)

    @classmethod
    def from_file(cls, path: Path) -> PCMAudio:
        if not path.exists():
            raise FileNotFoundError(f"audio file not found: {path}")
        if path.suffix.lower() == ".wav":
            return cls.from_wav_bytes(path.read_bytes())
        ffmpeg_bin = ensure_ffmpeg_available()
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-f",
            "wav",
            "-acodec",
            "pcm_s16le",
            "pipe:1",
        ]
        result = subprocess.run(cmd, capture_output=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg failed to read {path}: {stderr}")
        return cls.from_wav_bytes(result.stdout)

    def to_wav_bytes(self) -> bytes:
        buffer = BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(self.channels)
            handle.setsampwidth(self.sample_width)
            handle.setframerate(self.frame_rate)
            handle.writeframes(self.raw_data)
        return buffer.getvalue()

    def set_channels(self, target_channels: int) -> PCMAudio:
        if target_channels <= 0:
            raise ValueError("target_channels must be positive")
        if self.channels == target_channels or not self.raw_data:
            return PCMAudio(
                raw_data=self.raw_data,
                frame_rate=self.frame_rate,
                channels=target_channels,
            )

        samples = _bytes_to_int16_array(self.raw_data)
        frames = self.frame_count
        out = array.array("h")

        if target_channels == 1:
            src_ch = self.channels
            for frame in range(frames):
                base = frame * src_ch
                total = 0
                for ch in range(src_ch):
                    total += samples[base + ch]
                out.append(_clamp_int16(total / src_ch))
        elif self.channels == 1:
            for sample in samples:
                for _ in range(target_channels):
                    out.append(sample)
        else:
            # Downmix to mono first, then expand
            return self.set_channels(1).set_channels(target_channels)

        return PCMAudio(
            raw_data=_int16_array_to_bytes(out),
            frame_rate=self.frame_rate,
            channels=target_channels,
        )

    def set_frame_rate(self, target_rate: int) -> PCMAudio:
        if target_rate <= 0:
            raise ValueError("target_rate must be positive")
        if self.frame_rate == target_rate or not self.raw_data:
            return PCMAudio(
                raw_data=self.raw_data,
                frame_rate=target_rate,
                channels=self.channels,
            )

        src_frames = self.frame_count
        dst_frames = max(1, round(src_frames * target_rate / self.frame_rate))
        samples = _bytes_to_int16_array(self.raw_data)
        ch = self.channels
        out = array.array("h", [0] * (dst_frames * ch))
        ratio = self.frame_rate / target_rate

        for dst_idx in range(dst_frames):
            src_pos = dst_idx * ratio
            left = int(src_pos)
            frac = src_pos - left
            right = min(left + 1, src_frames - 1)
            if left >= src_frames:
                left = src_frames - 1
                right = left
                frac = 0.0
            dst_base = dst_idx * ch
            left_base = left * ch
            right_base = right * ch
            for c in range(ch):
                s0 = samples[left_base + c]
                s1 = samples[right_base + c]
                out[dst_base + c] = _clamp_int16(s0 + (s1 - s0) * frac)

        return PCMAudio(
            raw_data=_int16_array_to_bytes(out),
            frame_rate=target_rate,
            channels=self.channels,
        )

    def rms_dbfs(self) -> float:
        """Compute RMS loudness in dBFS (returns -inf for silent audio)."""
        if not self.raw_data:
            return -math.inf
        samples = _bytes_to_int16_array(self.raw_data)
        sum_sq = sum(s * s for s in samples)
        if sum_sq == 0:
            return -math.inf
        rms = math.sqrt(sum_sq / len(samples))
        return 20.0 * math.log10(rms / MAX_INT16)

    def peak_amplitude(self) -> int:
        if not self.raw_data:
            return 0
        samples = _bytes_to_int16_array(self.raw_data)
        return max(abs(s) for s in samples)

    def apply_gain_db(self, gain_db: float) -> PCMAudio:
        if not self.raw_data or abs(gain_db) < 1e-6:
            return self
        factor = 10.0 ** (gain_db / 20.0)
        samples = _bytes_to_int16_array(self.raw_data)
        scaled = array.array("h", (_clamp_int16(s * factor) for s in samples))
        return PCMAudio(
            raw_data=_int16_array_to_bytes(scaled),
            frame_rate=self.frame_rate,
            channels=self.channels,
        )

    def normalize_dbfs(self, target_dbfs: float = -16.0, *, max_peak: float = 0.95) -> PCMAudio:
        """Normalize audio RMS loudness to target_dbfs with peak ceiling protection."""
        current = self.rms_dbfs()
        if not math.isfinite(current):
            return self
        gain_db = target_dbfs - current
        peak = self.peak_amplitude()
        if peak > 0:
            max_gain_factor = (MAX_INT16 * max_peak) / peak
            max_gain_db = 20.0 * math.log10(max_gain_factor)
            gain_db = min(gain_db, max_gain_db)
        return self.apply_gain_db(gain_db)

    def export(
        self,
        output_file: Path,
        format: str = "mp3",
        *,
        tags: Mapping[str, str] | None = None,
    ) -> Path:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        normalized_fmt = format.lower()
        if normalized_fmt == "wav":
            output_file.write_bytes(self.to_wav_bytes())
            return output_file

        ffmpeg_bin = ensure_ffmpeg_available()
        ffmpeg_fmt = "ipod" if normalized_fmt == "m4a" else normalized_fmt
        cmd: list[str] = [
            ffmpeg_bin,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "wav",
            "-i",
            "pipe:0",
        ]
        if tags:
            for key, value in tags.items():
                cmd.extend(["-metadata", f"{key}={value}"])
        cmd.extend(["-f", ffmpeg_fmt, str(output_file)])
        result = subprocess.run(cmd, input=self.to_wav_bytes(), capture_output=True, check=False)
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"ffmpeg failed to export {output_file}: {stderr}")
        return output_file


def concatenate_pcm(segments: Sequence[PCMAudio]) -> PCMAudio:
    """Concatenate PCMAudio buffers in O(N) time, normalizing rate and channels."""
    if not segments:
        return PCMAudio.empty()

    reference = next((seg for seg in segments if seg.frame_count > 0), None)
    if reference is None:
        return PCMAudio.empty()

    frame_rate = reference.frame_rate
    channels = reference.channels
    chunks: list[bytes] = []
    for seg in segments:
        if seg.frame_count == 0:
            continue
        normalized = seg
        if normalized.frame_rate != frame_rate:
            normalized = normalized.set_frame_rate(frame_rate)
        if normalized.channels != channels:
            normalized = normalized.set_channels(channels)
        chunks.append(normalized.raw_data)

    return PCMAudio(raw_data=b"".join(chunks), frame_rate=frame_rate, channels=channels)


def mix_background_music(
    voice: PCMAudio,
    music: PCMAudio,
    *,
    speech_ranges_ms: Sequence[tuple[int, int]],
    music_gain_db: float = -6.0,
    duck_db: float = -12.0,
    attack_ms: int = 80,
    release_ms: int = 250,
    fade_out_ms: int = 1500,
) -> PCMAudio:
    """Loop/trim music beneath voice and smoothly duck music volume during spoken ranges."""
    if voice.frame_count == 0 or music.frame_count == 0:
        return voice

    target_rate = voice.frame_rate
    target_channels = max(voice.channels, music.channels)
    voice_norm = voice.set_channels(target_channels)
    music_norm = music.set_frame_rate(target_rate).set_channels(target_channels)

    total_frames = voice_norm.frame_count
    voice_samples = _bytes_to_int16_array(voice_norm.raw_data)
    music_samples = _bytes_to_int16_array(music_norm.raw_data)
    music_frames = music_norm.frame_count

    base_gain = 10.0 ** (music_gain_db / 20.0)
    ducked_gain = 10.0 ** ((music_gain_db + duck_db) / 20.0)

    # Compute smooth per-block (5ms) gain envelope
    block_frames = max(1, round(target_rate * 0.005))
    num_blocks = (total_frames + block_frames - 1) // block_frames
    block_is_speech = [False] * num_blocks

    for start_ms, end_ms in speech_ranges_ms:
        if end_ms <= start_ms:
            continue
        b_start = max(0, int((start_ms / 1000.0) * target_rate) // block_frames)
        b_end = min(num_blocks, int((end_ms / 1000.0) * target_rate) // block_frames + 1)
        for idx in range(b_start, b_end):
            block_is_speech[idx] = True

    attack_blocks = max(1.0, attack_ms / 5.0)
    release_blocks = max(1.0, release_ms / 5.0)
    fade_blocks = max(0, round(fade_out_ms / 5.0))

    gains: list[float] = [base_gain] * num_blocks
    current_gain = ducked_gain if (num_blocks > 0 and block_is_speech[0]) else base_gain
    for idx in range(num_blocks):
        target = ducked_gain if block_is_speech[idx] else base_gain
        if target < current_gain:
            step = (base_gain - ducked_gain) / attack_blocks
            current_gain = max(target, current_gain - step)
        elif target > current_gain:
            step = (base_gain - ducked_gain) / release_blocks
            current_gain = min(target, current_gain + step)
        if fade_blocks > 0 and idx >= num_blocks - fade_blocks:
            remaining = num_blocks - idx
            fade_scale = max(0.0, remaining / fade_blocks)
            gains[idx] = current_gain * fade_scale
        else:
            gains[idx] = current_gain

    out = array.array("h", [0] * (total_frames * target_channels))
    ch = target_channels
    for block_idx in range(num_blocks):
        gain = gains[block_idx]
        frame_start = block_idx * block_frames
        frame_end = min(total_frames, frame_start + block_frames)
        for frame in range(frame_start, frame_end):
            m_frame = frame % music_frames
            v_base = frame * ch
            m_base = m_frame * ch
            for c in range(ch):
                mixed = voice_samples[v_base + c] + music_samples[m_base + c] * gain
                out[v_base + c] = _clamp_int16(mixed)

    return PCMAudio(
        raw_data=_int16_array_to_bytes(out),
        frame_rate=target_rate,
        channels=target_channels,
    )
