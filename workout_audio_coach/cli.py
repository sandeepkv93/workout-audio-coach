from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from workout_audio_coach import audio as _audio
from workout_audio_coach import tts as _tts
from workout_audio_coach._version import __version__
from workout_audio_coach.config import (
    DEFAULT_COUNTDOWN_GAP_SECONDS,
    DEFAULT_SET_START_GAP_SECONDS,
    SUPPORTED_OUTPUT_FORMATS,
    SUPPORTED_TIMING_MODES,
    SUPPORTED_TTS_BACKENDS,
    TimingMode,
    TTSBackendName,
    WorkoutConfig,
    WorkoutStep,
    default_cache_dir,
    non_negative_float,
    non_negative_int,
    parse_rest_warnings,
    positive_float,
    positive_int,
    resolve_output_format,
)
from workout_audio_coach.localization import parse_phrase_override
from workout_audio_coach.planner import (
    build_workout_plan,
    format_workout_plan,
    maybe_write_script_preview,
)
from workout_audio_coach.tts import (
    TTSFactory,
    TTSWriter,
    audio_segment_from_mp3_bytes,
    phrase_cache_path,
    synthesize_phrase,
)

if TYPE_CHECKING:
    from pydub import AudioSegment

LOGGER = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_COUNTDOWN_GAP_SECONDS",
    "DEFAULT_SET_START_GAP_SECONDS",
    "SUPPORTED_OUTPUT_FORMATS",
    "TTSFactory",
    "TTSWriter",
    "WorkoutConfig",
    "WorkoutStep",
    "__version__",
    "audio_segment_from_mp3_bytes",
    "build_config",
    "build_workout_audio",
    "build_workout_plan",
    "create_combined_audio",
    "create_parser",
    "default_cache_dir",
    "format_workout_plan",
    "load_or_generate_segment",
    "main",
    "maybe_write_script_preview",
    "non_negative_float",
    "non_negative_int",
    "phrase_cache_path",
    "positive_float",
    "positive_int",
    "resolve_output_format",
    "synthesize_phrase",
]


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
) -> AudioSegment:
    return _tts.load_or_generate_segment(
        phrase,
        language,
        cache_dir,
        use_cache=use_cache,
        attempts=attempts,
        initial_backoff_seconds=initial_backoff_seconds,
        tts_factory=tts_factory,
        sleep_fn=sleep_fn,
        audio_decoder=audio_segment_from_mp3_bytes,
    )


def build_workout_audio(
    config: WorkoutConfig,
    *,
    plan: Sequence[WorkoutStep] | None = None,
) -> AudioSegment:
    return _audio.build_workout_audio(
        config,
        plan=plan,
        segment_loader=load_or_generate_segment,
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate or preview a guided workout audio file.")
    parser.add_argument(
        "--reps",
        type=positive_int,
        required=True,
        help="The number of reps in each set.",
    )
    parser.add_argument(
        "--sets",
        type=positive_int,
        required=True,
        help="The number of sets.",
    )
    parser.add_argument(
        "--rep-gap",
        "--rep_gap",
        dest="rep_gap",
        type=non_negative_float,
        required=True,
        help="The gap between reps in seconds.",
    )
    parser.add_argument(
        "--set-gap",
        "--set_gap",
        dest="set_gap",
        type=non_negative_float,
        required=True,
        help="The gap between sets in seconds.",
    )
    parser.add_argument(
        "--output-file",
        "--output_file",
        dest="output_file",
        type=Path,
        help="The output audio file name. Optional for preview-only runs.",
    )
    parser.add_argument(
        "--format",
        choices=SUPPORTED_OUTPUT_FORMATS,
        help="Output format. Defaults to the output file extension or mp3.",
    )
    parser.add_argument(
        "--language",
        default="en",
        help="Language code for speech synthesis and localized cues (e.g. en, es, fr, de).",
    )
    parser.add_argument(
        "--phrase",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Override a spoken cue template (e.g. --phrase rest='Take a breather').",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_cache_dir(),
        help="Directory used to cache generated speech clips.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the on-disk speech cache for this run.",
    )
    parser.add_argument(
        "--countdown",
        type=non_negative_int,
        default=3,
        help="Countdown seconds spoken before the first set. Use 0 to disable.",
    )
    parser.add_argument(
        "--countdown-gap",
        type=non_negative_float,
        default=DEFAULT_COUNTDOWN_GAP_SECONDS,
        help="Pause in seconds between countdown cues.",
    )
    parser.add_argument(
        "--countdown-end-gap",
        type=non_negative_float,
        default=0.0,
        help="Pause in seconds after the final countdown number before Set 1.",
    )
    parser.add_argument(
        "--timing-mode",
        choices=SUPPORTED_TIMING_MODES,
        default="gap",
        help="'gap' inserts full silence after speech; 'cadence' keeps fixed intervals.",
    )
    parser.add_argument(
        "--announce-rest",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Speak a rest cue before each set gap.",
    )
    parser.add_argument(
        "--rest-warnings",
        default="",
        help="Comma-separated seconds remaining to announce during rest (e.g. '10,3,2,1').",
    )
    parser.add_argument(
        "--announce-halfway",
        action="store_true",
        help="Speak a halfway cue mid-set (for sets with 4+ reps).",
    )
    parser.add_argument(
        "--announce-last-set",
        action="store_true",
        help="Speak a last-set cue at the start of the final set (for 2+ sets).",
    )
    parser.add_argument(
        "--set-start-gap",
        type=non_negative_float,
        default=DEFAULT_SET_START_GAP_SECONDS,
        help="Pause in seconds between the set announcement and the first rep.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Print the workout script instead of only writing audio.",
    )
    parser.add_argument(
        "--script-file",
        type=Path,
        help="Write the workout script preview to a text file.",
    )
    parser.add_argument(
        "--tts-backend",
        choices=SUPPORTED_TTS_BACKENDS,
        default="gtts",
        help="Speech backend: gtts (online), espeak/say (offline OS), or tone (offline beeps).",
    )
    parser.add_argument(
        "--tts-tld",
        default="com",
        help="Top-level domain for gTTS accent selection (e.g. com, co.uk, com.au).",
    )
    parser.add_argument(
        "--tts-slow",
        action="store_true",
        help="Use slower speech rate for gTTS synthesis.",
    )
    parser.add_argument(
        "--tts-voice",
        default=None,
        help="Voice name for local espeak or macOS say backends.",
    )
    parser.add_argument(
        "--beep-cues",
        action="store_true",
        help="Prepend synthesized audio tones before countdown, set, rest, and completion cues.",
    )
    parser.add_argument(
        "--tts-attempts",
        type=positive_int,
        default=3,
        help="Maximum speech synthesis attempts for each phrase.",
    )
    parser.add_argument(
        "--tts-backoff",
        type=positive_float,
        default=1.0,
        help="Initial retry backoff in seconds for speech synthesis.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def build_config(args: argparse.Namespace) -> WorkoutConfig:
    if args.output_file is None and not args.preview and args.script_file is None:
        raise ValueError("either --output-file or one of --preview/--script-file is required")

    raw_phrases: Sequence[str] = getattr(args, "phrase", None) or ()
    phrase_overrides = tuple(parse_phrase_override(item) for item in raw_phrases)
    raw_warnings: str = getattr(args, "rest_warnings", "") or ""
    rest_warnings = parse_rest_warnings(raw_warnings)
    timing_mode: TimingMode = getattr(args, "timing_mode", "gap")
    tts_backend: TTSBackendName = getattr(args, "tts_backend", "gtts")

    return WorkoutConfig(
        reps=args.reps,
        sets=args.sets,
        rep_gap=args.rep_gap,
        set_gap=args.set_gap,
        output_file=args.output_file,
        output_format=resolve_output_format(args.output_file, args.format),
        language=args.language,
        cache_dir=args.cache_dir,
        use_cache=not args.no_cache,
        countdown=args.countdown,
        announce_rest=args.announce_rest,
        set_start_gap=args.set_start_gap,
        preview=args.preview,
        script_file=args.script_file,
        tts_attempts=args.tts_attempts,
        tts_initial_backoff=args.tts_backoff,
        phrase_overrides=phrase_overrides,
        timing_mode=timing_mode,
        countdown_gap=getattr(args, "countdown_gap", DEFAULT_COUNTDOWN_GAP_SECONDS),
        countdown_end_gap=getattr(args, "countdown_end_gap", 0.0),
        rest_warnings=rest_warnings,
        announce_halfway=bool(getattr(args, "announce_halfway", False)),
        announce_last_set=bool(getattr(args, "announce_last_set", False)),
        tts_backend=tts_backend,
        tts_tld=str(getattr(args, "tts_tld", "com")),
        tts_slow=bool(getattr(args, "tts_slow", False)),
        tts_voice=getattr(args, "tts_voice", None),
        beep_cues=bool(getattr(args, "beep_cues", False)),
    )


def create_combined_audio(args: argparse.Namespace | WorkoutConfig) -> Path | None:
    config = args if isinstance(args, WorkoutConfig) else build_config(args)
    plan = build_workout_plan(config)
    maybe_write_script_preview(config, plan)

    if config.output_file is None:
        LOGGER.info("Preview-only run completed without audio export.")
        return None

    output_format = config.output_format or "mp3"
    LOGGER.info(
        "Generating workout audio: %s sets x %s reps to %s",
        config.sets,
        config.reps,
        config.output_file,
    )
    combined_audio = build_workout_audio(config, plan=plan)
    _audio.export_workout_audio(combined_audio, config.output_file, output_format)
    LOGGER.info("Audio file created: %s", config.output_file)
    return config.output_file


def main(argv: Sequence[str] | None = None) -> None:
    parser = create_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )
    try:
        create_combined_audio(args)
    except ValueError as exc:
        parser.error(str(exc))
    except (RuntimeError, OSError) as exc:
        LOGGER.error("%s", exc)
        sys.exit(1)
