from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from workout_audio_coach import audio as _audio
from workout_audio_coach import tts as _tts
from workout_audio_coach._version import __version__
from workout_audio_coach.config import (
    DEFAULT_COUNTDOWN_GAP_SECONDS,
    DEFAULT_SET_START_GAP_SECONDS,
    SUPPORTED_OUTPUT_FORMATS,
    SUPPORTED_TIMING_MODES,
    SUPPORTED_TTS_BACKENDS,
    TempoSpec,
    TimingMode,
    TTSBackendName,
    WorkoutConfig,
    WorkoutStep,
    default_cache_dir,
    finite_float,
    non_negative_float,
    non_negative_int,
    parse_rest_warnings,
    parse_tempo,
    positive_float,
    positive_int,
    resolve_output_format,
)
from workout_audio_coach.live import run_live_coach
from workout_audio_coach.localization import parse_phrase_override
from workout_audio_coach.pcm import PCMAudio
from workout_audio_coach.planner import (
    build_workout_plan,
    format_workout_plan,
    maybe_write_script_preview,
)
from workout_audio_coach.routines import (
    PRESET_NAMES,
    WorkoutRoutine,
    format_preset_list,
    get_preset_routine,
    load_routine_file,
)
from workout_audio_coach.timeline import (
    build_estimated_timeline,
    export_timeline,
)
from workout_audio_coach.tts import (
    TTSFactory,
    TTSWriter,
    audio_segment_from_mp3_bytes,
    clear_cache,
    format_cache_stats,
    get_cache_stats,
    phrase_cache_path,
    synthesize_phrase,
)

LOGGER = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_COUNTDOWN_GAP_SECONDS",
    "DEFAULT_SET_START_GAP_SECONDS",
    "PRESET_NAMES",
    "SUPPORTED_OUTPUT_FORMATS",
    "SUPPORTED_TIMING_MODES",
    "SUPPORTED_TTS_BACKENDS",
    "PCMAudio",
    "TTSFactory",
    "TTSWriter",
    "WorkoutConfig",
    "WorkoutRoutine",
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
) -> PCMAudio:
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
) -> PCMAudio:
    return _audio.build_workout_audio(
        config,
        plan=plan,
        segment_loader=load_or_generate_segment,
    )


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate or preview a guided workout audio file.")
    parser.add_argument(
        "--routine",
        type=Path,
        default=None,
        help="Path to a structured TOML or JSON multi-exercise workout routine file.",
    )
    parser.add_argument(
        "--preset",
        choices=PRESET_NAMES,
        default=None,
        help="Use a built-in workout preset instead of manual set/rep arguments.",
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="List available built-in workout presets and exit.",
    )
    parser.add_argument(
        "--reps",
        type=positive_int,
        default=None,
        help="The number of reps in each set (for rep-based workouts).",
    )
    parser.add_argument(
        "--duration",
        type=positive_float,
        default=None,
        help="Work duration in seconds for each round (for timed interval workouts).",
    )
    parser.add_argument(
        "--sets",
        type=positive_int,
        default=None,
        help="The number of sets or rounds.",
    )
    parser.add_argument(
        "--rep-gap",
        "--rep_gap",
        dest="rep_gap",
        type=non_negative_float,
        default=None,
        help="The gap between reps in seconds.",
    )
    parser.add_argument(
        "--set-gap",
        "--set_gap",
        dest="set_gap",
        type=non_negative_float,
        default=None,
        help="The gap between sets/rounds in seconds.",
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
        default=None,
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
        "--cache-stats",
        action="store_true",
        help="Print speech cache usage statistics and exit.",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help="Remove cached speech clips from --cache-dir and exit.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable the on-disk speech cache for this run.",
    )
    parser.add_argument(
        "--countdown",
        type=non_negative_int,
        default=None,
        help="Countdown seconds spoken before the first set. Use 0 to disable (default: 3).",
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
        default=None,
        help="'gap' inserts full silence after speech; 'cadence' keeps fixed intervals.",
    )
    parser.add_argument(
        "--tempo",
        default=None,
        help="Rep tempo coaching in ECC-PAUSE-CONC[-TOP] seconds (e.g. '3-1-1').",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the workout live in the terminal with progress display and interactive controls.",
    )
    parser.add_argument(
        "--live-silent",
        action="store_true",
        help="Run --live visually without local audio playback.",
    )
    parser.add_argument(
        "--announce-rest",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Speak a rest cue before each set gap (default: enabled).",
    )
    parser.add_argument(
        "--rest-warnings",
        default=None,
        help="Comma-separated seconds remaining to announce during rest (e.g. '10,3,2,1').",
    )
    parser.add_argument(
        "--announce-halfway",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Speak a halfway cue mid-set or mid-interval.",
    )
    parser.add_argument(
        "--announce-last-set",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Speak a last-set cue at the start of the final set.",
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
        "--timestamps-file",
        type=Path,
        default=None,
        help="Export timestamped cue sheet (.vtt, .srt, .lrc, or .json).",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Custom workout title used in preview output and audio metadata tags.",
    )
    parser.add_argument(
        "--tts-backend",
        choices=SUPPORTED_TTS_BACKENDS,
        default="gtts",
        help="Speech backend: gtts, edge (neural), piper (offline neural), espeak, say, or tone.",
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
        help="Voice name (edge/espeak/say) or ONNX model path (piper).",
    )
    parser.add_argument(
        "--tts-workers",
        type=positive_int,
        default=4,
        help="Maximum concurrent workers used for TTS phrase synthesis (default: 4).",
    )
    parser.add_argument(
        "--beep-cues",
        action="store_true",
        help="Prepend synthesized audio tones before countdown, set, rest, and completion cues.",
    )
    parser.add_argument(
        "--normalize",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Normalize speech and tone clips to a consistent loudness target (--target-dbfs).",
    )
    parser.add_argument(
        "--target-dbfs",
        type=finite_float,
        default=-16.0,
        help="Target RMS loudness in dBFS when --normalize is enabled (default: -16.0).",
    )
    parser.add_argument(
        "--music",
        type=Path,
        default=None,
        help="Background music audio file to loop/mix beneath the workout.",
    )
    parser.add_argument(
        "--music-gain-db",
        type=finite_float,
        default=-6.0,
        help="Base volume adjustment in dB for --music (default: -6.0).",
    )
    parser.add_argument(
        "--duck-db",
        type=finite_float,
        default=-12.0,
        help="Additional dB reduction applied to --music while the coach speaks (default: -12.0).",
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


def _resolve_routine(args: argparse.Namespace) -> WorkoutRoutine | None:
    routine_path: Path | None = getattr(args, "routine", None)
    preset_name: str | None = getattr(args, "preset", None)
    if routine_path is not None and preset_name is not None:
        raise ValueError("cannot specify both --routine and --preset")
    if routine_path is not None:
        return load_routine_file(routine_path)
    if preset_name is not None:
        return get_preset_routine(preset_name)
    return None


def build_config(args: argparse.Namespace) -> WorkoutConfig:
    timestamps_file: Path | None = getattr(args, "timestamps_file", None)
    live_mode: bool = bool(getattr(args, "live", False))
    if (
        args.output_file is None
        and not args.preview
        and args.script_file is None
        and timestamps_file is None
        and not live_mode
    ):
        raise ValueError(
            "either --output-file or one of --preview/--script-file/--timestamps-file/--live "
            "is required"
        )

    routine = _resolve_routine(args)
    duration: float | None = getattr(args, "duration", None)

    reps: int = 0
    sets: int = 0
    rep_gap: float = 0.0
    set_gap: float = 0.0

    if routine is not None:
        sets = routine.total_set_count()
    elif duration is not None:
        if args.reps is not None:
            raise ValueError("cannot specify both --duration and --reps")
        if args.sets is None:
            raise ValueError("--sets is required when using --duration")
        if args.set_gap is None:
            raise ValueError("--set-gap is required when using --duration")
        sets = args.sets
        set_gap = args.set_gap
    else:
        missing = [
            flag
            for flag, value in (
                ("--reps", args.reps),
                ("--sets", args.sets),
                ("--rep-gap", args.rep_gap),
                ("--set-gap", args.set_gap),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                f"the following arguments are required unless --routine, --preset, "
                f"or --duration is used: {', '.join(missing)}"
            )
        reps = args.reps
        sets = args.sets
        rep_gap = args.rep_gap
        set_gap = args.set_gap

    raw_phrases: Sequence[str] = getattr(args, "phrase", None) or ()
    cli_phrase_overrides = tuple(parse_phrase_override(item) for item in raw_phrases)
    merged_phrases: dict[str, str] = {}
    if routine is not None:
        merged_phrases.update(routine.phrase_overrides)
    merged_phrases.update(cli_phrase_overrides)

    language: str = (
        args.language
        if args.language is not None
        else (routine.language if routine is not None and routine.language is not None else "en")
    )
    countdown: int = (
        args.countdown
        if args.countdown is not None
        else (routine.countdown if routine is not None and routine.countdown is not None else 3)
    )
    announce_rest: bool = (
        args.announce_rest
        if args.announce_rest is not None
        else (
            routine.announce_rest
            if routine is not None and routine.announce_rest is not None
            else True
        )
    )
    timing_mode_arg: TimingMode | None = getattr(args, "timing_mode", None)
    timing_mode: TimingMode = (
        timing_mode_arg
        if timing_mode_arg is not None
        else (
            routine.timing_mode
            if routine is not None and routine.timing_mode is not None
            else "gap"
        )
    )
    raw_warnings: str | None = getattr(args, "rest_warnings", None)
    if raw_warnings is not None:
        rest_warnings = parse_rest_warnings(raw_warnings)
    elif routine is not None and routine.rest_warnings is not None:
        rest_warnings = routine.rest_warnings
    else:
        rest_warnings = ()

    announce_halfway_arg: bool | None = getattr(args, "announce_halfway", None)
    announce_halfway = (
        announce_halfway_arg
        if announce_halfway_arg is not None
        else (
            routine.announce_halfway
            if routine is not None and routine.announce_halfway is not None
            else False
        )
    )
    announce_last_set_arg: bool | None = getattr(args, "announce_last_set", None)
    announce_last_set = (
        announce_last_set_arg
        if announce_last_set_arg is not None
        else (
            routine.announce_last_set
            if routine is not None and routine.announce_last_set is not None
            else False
        )
    )

    raw_tempo: str | None = getattr(args, "tempo", None)
    tempo: TempoSpec | None = parse_tempo(raw_tempo) if raw_tempo is not None else None
    tts_backend: TTSBackendName = getattr(args, "tts_backend", "gtts")

    return WorkoutConfig(
        reps=reps,
        sets=sets,
        rep_gap=rep_gap,
        set_gap=set_gap,
        output_file=args.output_file,
        output_format=resolve_output_format(args.output_file, args.format),
        language=language,
        cache_dir=args.cache_dir,
        use_cache=not args.no_cache,
        countdown=countdown,
        announce_rest=announce_rest,
        set_start_gap=args.set_start_gap,
        preview=args.preview,
        script_file=args.script_file,
        tts_attempts=args.tts_attempts,
        tts_initial_backoff=args.tts_backoff,
        phrase_overrides=tuple(merged_phrases.items()),
        timing_mode=timing_mode,
        countdown_gap=getattr(args, "countdown_gap", DEFAULT_COUNTDOWN_GAP_SECONDS),
        countdown_end_gap=getattr(args, "countdown_end_gap", 0.0),
        rest_warnings=rest_warnings,
        announce_halfway=announce_halfway,
        announce_last_set=announce_last_set,
        tts_backend=tts_backend,
        tts_tld=str(getattr(args, "tts_tld", "com")),
        tts_slow=bool(getattr(args, "tts_slow", False)),
        tts_voice=getattr(args, "tts_voice", None),
        beep_cues=bool(getattr(args, "beep_cues", False)),
        duration=duration,
        routine=routine,
        timestamps_file=timestamps_file,
        title=getattr(args, "title", None),
        normalize_audio=bool(getattr(args, "normalize", False)),
        target_dbfs=float(getattr(args, "target_dbfs", -16.0)),
        music_file=getattr(args, "music", None),
        music_gain_db=float(getattr(args, "music_gain_db", -6.0)),
        duck_db=float(getattr(args, "duck_db", -12.0)),
        tts_workers=int(getattr(args, "tts_workers", 4)),
        tempo=tempo,
        live=live_mode,
        live_silent=bool(getattr(args, "live_silent", False)),
    )


def create_combined_audio(args: argparse.Namespace | WorkoutConfig) -> Path | None:
    config = args if isinstance(args, WorkoutConfig) else build_config(args)
    plan = build_workout_plan(config)
    maybe_write_script_preview(config, plan)

    if config.live:
        run_live_coach(config, plan, silent=config.live_silent)
        if config.output_file is None:
            if config.timestamps_file is not None:
                export_timeline(build_estimated_timeline(plan), config.timestamps_file)
            return None

    if config.output_file is None:
        if config.timestamps_file is not None:
            estimated = build_estimated_timeline(plan)
            export_timeline(estimated, config.timestamps_file)
            LOGGER.info("Estimated timestamps written to %s", config.timestamps_file)
        LOGGER.info("Preview-only run completed without audio export.")
        return None

    output_format = config.output_format or "mp3"
    if config.routine is not None:
        LOGGER.info(
            "Generating workout audio for routine %r to %s",
            config.routine.name,
            config.output_file,
        )
    elif config.duration is not None:
        LOGGER.info(
            "Generating timed workout audio: %s x %gs to %s",
            config.sets,
            config.duration,
            config.output_file,
        )
    else:
        LOGGER.info(
            "Generating workout audio: %s sets x %s reps to %s",
            config.sets,
            config.reps,
            config.output_file,
        )

    if config.timestamps_file is not None:
        combined_audio, timeline = _audio.build_workout_audio_with_timeline(
            config,
            plan=plan,
            segment_loader=load_or_generate_segment,
        )
        export_timeline(timeline, config.timestamps_file)
        LOGGER.info("Exact timestamps written to %s", config.timestamps_file)
    else:
        combined_audio = build_workout_audio(config, plan=plan)

    tags = _audio.build_audio_metadata_tags(config)
    _audio.export_workout_audio(combined_audio, config.output_file, output_format, tags=tags)
    LOGGER.info("Audio file created: %s", config.output_file)
    return config.output_file


def main(argv: Sequence[str] | None = None) -> None:
    parser = create_parser()
    args = parser.parse_args(argv)
    if args.list_presets:
        print(format_preset_list())
        return
    if args.clear_cache:
        cleared = clear_cache(args.cache_dir)
        print(f"Cleared {cleared.file_count} cached clips from {cleared.cache_dir}")
        return
    if args.cache_stats:
        print(format_cache_stats(get_cache_stats(args.cache_dir)))
        return
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
