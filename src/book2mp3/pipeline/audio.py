from __future__ import annotations

import array
import re
import subprocess
import sys
import wave
from pathlib import Path
import logging

try:
    import imageio_ffmpeg
except ModuleNotFoundError:  # pragma: no cover - exercised in CLI/API dependency smoke
    imageio_ffmpeg = None

from book2mp3.utils.perf_logging import perf_scope


def ffmpeg_executable() -> str:
    if imageio_ffmpeg is None:
        raise ModuleNotFoundError(
            "imageio_ffmpeg is not installed. Install the audio runtime dependencies before synthesizing or exporting audio."
        )
    return imageio_ffmpeg.get_ffmpeg_exe()


def _ffmpeg_concat_entry(path: Path) -> str:
    escaped = path.resolve().as_posix().replace("'", "'\\''")
    return f"file '{escaped}'"


def _ffmetadata_escape(value: str) -> str:
    escaped = value.replace("\\", "\\\\")
    escaped = escaped.replace(";", "\\;").replace("#", "\\#").replace("=", "\\=")
    return escaped.replace("\n", "\\\n")


def _run_ffmpeg(cmd: list[str], logger: logging.Logger | None = None, *, context: str) -> subprocess.CompletedProcess[str]:
    with perf_scope("ffmpeg.run", category="audio", context=context, command=cmd):
        if logger:
            logger.debug("%s with command: %s", context, cmd)
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            if logger:
                logger.debug("FFmpeg stdout: %s", result.stdout.strip())
                logger.debug("FFmpeg stderr: %s", result.stderr.strip())
            return result
        except subprocess.CalledProcessError as exc:
            if logger:
                logger.exception("%s failed", context)
                logger.debug("FFmpeg stdout: %s", exc.stdout)
                logger.debug("FFmpeg stderr: %s", exc.stderr)
            raise


def probe_media_duration_seconds(path: Path, logger: logging.Logger | None = None) -> float:
    with perf_scope("media.duration_probe", category="audio", path=path):
        cmd = [
            ffmpeg_executable(),
            "-i",
            str(path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = f"{result.stdout}\n{result.stderr}"
        match = re.search(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)", output)
        if not match:
            raise RuntimeError(f"Could not read media duration for {path}")
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float(match.group(3))
        duration = hours * 3600 + minutes * 60 + seconds
        if logger:
            logger.debug("Probed media duration for %s: %.3fs", path, duration)
        return duration


def _wav_rms(samples: array.array) -> float:
    if not samples:
        return 0.0
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


def trim_wav_silence_in_place(
    wav_path: Path,
    *,
    threshold_db: float = -45.0,
    window_ms: int = 20,
    keep_leading_ms: int = 120,
    keep_internal_ms: int = 900,
    keep_trailing_ms: int = 650,
    min_removed_ms: int = 1000,
    logger: logging.Logger | None = None,
) -> bool:
    """Compress excessive silence from a PCM WAV file.

    XTTS can emit long silent gaps or tails for short chunks. This keeps short
    natural pauses but removes generated dead air before MP3 conversion or concat.
    """
    if not wav_path.exists():
        return False
    try:
        with wave.open(str(wav_path), "rb") as wav_file:
            params = wav_file.getparams()
            raw_frames = wav_file.readframes(params.nframes)
    except (wave.Error, OSError):
        return False

    if params.nframes <= 0 or params.sampwidth != 2:
        return False

    samples = array.array("h")
    samples.frombytes(raw_frames)
    if sys.byteorder != "little":
        samples.byteswap()
    if not samples:
        return False

    channels = max(1, params.nchannels)
    frame_count = min(params.nframes, len(samples) // channels)
    if frame_count <= 0:
        return False

    threshold = max(1, int(32767 * (10 ** (threshold_db / 20))))
    window_frames = max(1, int(params.framerate * window_ms / 1000))
    keep_leading_frames = max(0, int(params.framerate * keep_leading_ms / 1000))
    keep_trailing_frames = max(0, int(params.framerate * keep_trailing_ms / 1000))
    min_removed_frames = max(0, int(params.framerate * min_removed_ms / 1000))

    windows: list[tuple[int, int, bool]] = []
    for start_frame in range(0, frame_count, window_frames):
        end_frame = min(frame_count, start_frame + window_frames)
        start_sample = start_frame * channels
        end_sample = end_frame * channels
        is_loud = _wav_rms(samples[start_sample:end_sample]) > threshold
        windows.append((start_frame, end_frame, is_loud))

    loud_windows = [(start, end) for start, end, is_loud in windows if is_loud]
    if not loud_windows:
        return False

    first_loud_start, _ = loud_windows[0]
    _, last_loud_end = loud_windows[-1]
    keep_internal_frames = max(0, int(params.framerate * keep_internal_ms / 1000))

    kept = array.array("h")
    kept_frames = 0
    index = 0
    while index < len(windows):
        run_start_frame, run_end_frame, run_is_loud = windows[index]
        index += 1
        while index < len(windows) and windows[index][2] == run_is_loud:
            run_end_frame = windows[index][1]
            index += 1

        keep_start = run_start_frame
        keep_end = run_end_frame
        if not run_is_loud:
            run_frames = run_end_frame - run_start_frame
            if run_end_frame <= first_loud_start:
                keep_frames = min(run_frames, keep_leading_frames)
                keep_start = run_end_frame - keep_frames
            elif run_start_frame >= last_loud_end:
                keep_frames = min(run_frames, keep_trailing_frames)
                keep_end = run_start_frame + keep_frames
            else:
                keep_frames = min(run_frames, keep_internal_frames)
                keep_end = run_start_frame + keep_frames

        if keep_end <= keep_start:
            continue
        kept.extend(samples[keep_start * channels : keep_end * channels])
        kept_frames += keep_end - keep_start

    removed_frames = frame_count - kept_frames
    if removed_frames < min_removed_frames:
        return False
    if kept_frames >= frame_count:
        return False

    trimmed_samples = kept
    if sys.byteorder != "little":
        trimmed_samples.byteswap()
    temp_path = wav_path.with_name(f".{wav_path.name}.trimmed")
    try:
        with wave.open(str(temp_path), "wb") as trimmed_file:
            trimmed_file.setnchannels(params.nchannels)
            trimmed_file.setsampwidth(params.sampwidth)
            trimmed_file.setframerate(params.framerate)
            trimmed_file.setcomptype(params.comptype, params.compname)
            trimmed_file.writeframes(trimmed_samples.tobytes())
        temp_path.replace(wav_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    if logger:
        original_seconds = frame_count / params.framerate
        trimmed_seconds = kept_frames / params.framerate
        logger.info(
            "Compressed XTTS WAV silence: %s %.2fs -> %.2fs (removed %.2fs)",
            wav_path.name,
            original_seconds,
            trimmed_seconds,
            original_seconds - trimmed_seconds,
        )
    return True


def write_ffmetadata_file(
    target: Path,
    metadata: dict[str, str],
    chapters: list[dict[str, int | str]] | None = None,
) -> Path:
    lines = [";FFMETADATA1"]
    for key, value in metadata.items():
        if value:
            lines.append(f"{key}={_ffmetadata_escape(str(value))}")
    for chapter in chapters or []:
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={int(chapter['start_ms'])}",
                f"END={int(chapter['end_ms'])}",
                f"title={_ffmetadata_escape(str(chapter['title']))}",
            ]
        )
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def _is_image_path(path: Path) -> bool:
    suffix = path.suffix.lower()
    return suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


def apply_mp3_metadata(
    input_path: Path,
    output_path: Path,
    metadata: dict[str, str],
    *,
    logger: logging.Logger | None = None,
    chapters: list[dict[str, int | str]] | None = None,
    cover_art_file: str | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cover_path = Path(cover_art_file) if cover_art_file else None
    if cover_path is not None and not cover_path.exists():
        cover_path = None
    if cover_path is not None and not _is_image_path(cover_path):
        cover_path = None
    ffmetadata_file = output_path.parent / f"{output_path.stem}__metadata.txt"
    write_ffmetadata_file(ffmetadata_file, metadata, chapters)
    try:
        if cover_path is not None:
            cmd = [
                ffmpeg_executable(),
                "-y",
                "-i",
                str(input_path),
                "-i",
                str(cover_path),
                "-i",
                str(ffmetadata_file),
                "-map_metadata",
                "2",
                "-map",
                "0:a",
                "-map",
                "1:v",
                "-c:a",
                "copy",
                "-c:v",
                "mjpeg",
                "-disposition:v:0",
                "attached_pic",
                "-id3v2_version",
                "3",
                str(output_path),
            ]
        else:
            cmd = [
                ffmpeg_executable(),
                "-y",
                "-i",
                str(input_path),
                "-i",
                str(ffmetadata_file),
                "-map_metadata",
                "1",
                "-codec",
                "copy",
                str(output_path),
            ]
        _run_ffmpeg(cmd, logger=logger, context="Applying MP3 metadata")
    finally:
        if ffmetadata_file.exists():
            ffmetadata_file.unlink()


def apply_mp3_metadata_in_place(
    path: Path,
    metadata: dict[str, str],
    *,
    logger: logging.Logger | None = None,
    chapters: list[dict[str, int | str]] | None = None,
    cover_art_file: str | None = None,
) -> None:
    temp_output = path.with_name(f"{path.stem}__tagged{path.suffix}")
    apply_mp3_metadata(
        path,
        temp_output,
        metadata,
        logger=logger,
        chapters=chapters,
        cover_art_file=cover_art_file,
    )
    temp_output.replace(path)


def wav_to_mp3(wav_path: Path, mp3_path: Path, logger: logging.Logger | None = None) -> None:
    mp3_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_executable(),
        "-y",
        "-i",
        str(wav_path),
        "-codec:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(mp3_path),
    ]
    _run_ffmpeg(cmd, logger=logger, context="Converting WAV to MP3")


def concat_mp3_files(
    inputs: list[Path], output_path: Path, logger: logging.Logger | None = None
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = output_path.parent / f"{output_path.stem}_concat.txt"
    list_file.write_text(
        "\n".join(_ffmpeg_concat_entry(path) for path in inputs),
        encoding="utf-8",
    )
    try:
        cmd = [
            ffmpeg_executable(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(output_path),
        ]
        _run_ffmpeg(cmd, logger=logger, context="Concatenating MP3 files")
    finally:
        if list_file.exists():
            list_file.unlink()


def concat_audio_files_to_mp3(
    inputs: list[Path],
    output_path: Path,
    logger: logging.Logger | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = output_path.parent / f"{output_path.stem}_concat.txt"
    list_file.write_text(
        "\n".join(_ffmpeg_concat_entry(path) for path in inputs),
        encoding="utf-8",
    )
    try:
        cmd = [
            ffmpeg_executable(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "2",
            str(output_path),
        ]
        _run_ffmpeg(cmd, logger=logger, context="Concatenating audio files to MP3")
    finally:
        if list_file.exists():
            list_file.unlink()


def segment_mp3_file(
    input_path: Path,
    output_pattern: Path,
    segment_seconds: int,
    logger: logging.Logger | None = None,
) -> list[Path]:
    output_pattern.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg_executable(),
        "-y",
        "-i",
        str(input_path),
        "-f",
        "segment",
        "-segment_time",
        str(segment_seconds),
        "-reset_timestamps",
        "1",
        "-c",
        "copy",
        str(output_pattern),
    ]
    _run_ffmpeg(cmd, logger=logger, context="Segmenting MP3")
    return sorted(output_pattern.parent.glob(output_pattern.name.replace("%03d", "*")))
