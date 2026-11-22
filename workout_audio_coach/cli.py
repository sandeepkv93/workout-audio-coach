from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from gtts import gTTS
from pydub import AudioSegment

from workout_audio_coach import audio as _audio
from workout_audio_coach import tts as _tts
from workout_audio_coach._version import __version__
from workout_audio_coach.config import (
    DEFAULT_COUNTDOWN_GAP_SECONDS,
    DEFAULT_SET_START_GAP_SECONDS,
    SUPPORTED_OUTPUT_FORMATS,
    WorkoutConfig,
    WorkoutStep,
    default_cache_dir,
    non_negative_float,
    non_negative_int,
    positive_float,
    positive_int,
    resolve_output_format,
)
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
    tts_factory: TTSFactory = gTTS,
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
        help="Language to use for gTTS speech synthesis.",
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
        "--announce-rest",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Speak a rest cue before each set gap.",
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
    )


def create_combined_audio(args: argparse.Namespace | WorkoutConfig) -> Path | None:
    config = args if isinstance(args, WorkoutConfig) else build_config(args)
    plan = build_workout_plan(config)
    maybe_write_script_preview(config, plan)

    if config.output_file is None:
        LOGGER.info("Preview-only run completed without audio export.")
        return None

    LOGGER.info(
        "Generating workout audio: %s sets x %s reps to %s",
        config.sets,
        config.reps,
        config.output_file,
    )
    combined_audio = build_workout_audio(config, plan=plan)
    config.output_file.parent.mkdir(parents=True, exist_ok=True)
    combined_audio.export(config.output_file, format=config.output_format)
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
