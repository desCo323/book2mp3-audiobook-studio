from __future__ import annotations

import re
import subprocess
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


def apply_mp3_metadata(
    input_path: Path,
    output_path: Path,
    metadata: dict[str, str],
    *,
    logger: logging.Logger | None = None,
    chapters: list[dict[str, int | str]] | None = None,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmetadata_file = output_path.parent / f"{output_path.stem}__metadata.txt"
    write_ffmetadata_file(ffmetadata_file, metadata, chapters)
    try:
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
) -> None:
    temp_output = path.with_name(f"{path.stem}__tagged{path.suffix}")
    apply_mp3_metadata(path, temp_output, metadata, logger=logger, chapters=chapters)
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
