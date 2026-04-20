from __future__ import annotations

import subprocess
from pathlib import Path
import logging

import imageio_ffmpeg


def ffmpeg_executable() -> str:
    return imageio_ffmpeg.get_ffmpeg_exe()


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
    if logger:
        logger.debug("Converting WAV to MP3 with command: %s", cmd)
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if logger:
            logger.debug("FFmpeg stdout: %s", result.stdout.strip())
            logger.debug("FFmpeg stderr: %s", result.stderr.strip())
    except subprocess.CalledProcessError as exc:
        if logger:
            logger.exception("FFmpeg WAV->MP3 conversion failed")
            logger.debug("FFmpeg stdout: %s", exc.stdout)
            logger.debug("FFmpeg stderr: %s", exc.stderr)
        raise


def concat_mp3_files(
    inputs: list[Path], output_path: Path, logger: logging.Logger | None = None
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    list_file = output_path.parent / f"{output_path.stem}_concat.txt"
    list_file.write_text(
        "\n".join(f"file '{path.resolve().as_posix()}'" for path in inputs),
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
        if logger:
            logger.debug("Concatenating MP3 files with command: %s", cmd)
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if logger:
            logger.debug("FFmpeg concat stdout: %s", result.stdout.strip())
            logger.debug("FFmpeg concat stderr: %s", result.stderr.strip())
    finally:
        if list_file.exists():
            list_file.unlink()
