from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
import re

from book2mp3.pipeline.chunking import split_text


QUOTE_RE = re.compile(r"[\u0022\u0027\u00ab\u00bb\u2018\u2019\u201a\u201c\u201d\u201e]")
LEADING_DIALOGUE_RE = re.compile(r"^\s*[-\u2013\u2014]\s*\S")
ELLIPSIS_RE = re.compile(r"(?:\.\.\.|\u2026)")
SENTENCE_RE = re.compile(r"[^.!?\u2026]+(?:[.!?]+|\u2026+)[\u0022\u0027\u00ab\u00bb\u2018\u2019\u201a\u201c\u201d\u201e]*|[^.!?\u2026]+$")
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ProsodySegment:
    text: str
    style: str
    pause_after_ms: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ProsodyChunk:
    text: str
    style: str
    pause_after_ms: int
    reasons: tuple[str, ...]
    segment_count: int
    name_marker_score: int = 0


def normalize_prosody_text(text: str) -> str:
    return SPACE_RE.sub(" ", str(text or "")).strip()


def _language_for_pysbd(language_code: str) -> str:
    normalized = (language_code or "de").strip().lower().replace("_", "-")
    primary = normalized.split("-", 1)[0]
    return primary or "de"


def _paragraphs(text: str) -> list[str]:
    blocks = [block for block in re.split(r"(?:\r?\n\s*){2,}", text or "") if block.strip()]
    if not blocks:
        return []
    paragraphs: list[str] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        sentence_like_lines = sum(1 for line in lines if re.search(r"[.!?\u2026][\u0022\u0027\u00bb\u201c\u201d]?$", line))
        dialogue_lines = sum(1 for line in lines if LEADING_DIALOGUE_RE.search(line) or QUOTE_RE.search(line))
        if len(lines) > 1 and (sentence_like_lines + dialogue_lines) >= max(2, len(lines) // 2):
            paragraphs.extend(lines)
        else:
            paragraphs.append(" ".join(lines))
    return [normalize_prosody_text(paragraph) for paragraph in paragraphs if normalize_prosody_text(paragraph)]


def _pysbd_sentences(text: str, *, language_code: str) -> list[str] | None:
    try:
        import pysbd  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return None
    try:
        segmenter = pysbd.Segmenter(language=_language_for_pysbd(language_code), clean=False)
        sentences = segmenter.segment(text)
    except Exception:
        return None
    return [normalize_prosody_text(sentence) for sentence in sentences if normalize_prosody_text(sentence)]


def _regex_sentences(text: str) -> list[str]:
    return [normalize_prosody_text(match.group(0)) for match in SENTENCE_RE.finditer(text) if normalize_prosody_text(match.group(0))]


def _sentences(text: str, *, language_code: str) -> list[str]:
    return _pysbd_sentences(text, language_code=language_code) or _regex_sentences(text) or [normalize_prosody_text(text)]


def _style_for_sentence(text: str) -> tuple[str, list[str]]:
    stripped = text.strip()
    reasons: list[str] = []
    has_dialogue = bool(QUOTE_RE.search(stripped) or LEADING_DIALOGUE_RE.search(stripped))
    has_question = stripped.endswith("?") or re.search(r"\?[\u0022\u0027\u00bb\u201c\u201d]?$", stripped) is not None
    has_exclaim = stripped.endswith("!") or re.search(r"![\u0022\u0027\u00bb\u201c\u201d]?$", stripped) is not None
    has_ellipsis = ELLIPSIS_RE.search(stripped) is not None

    if has_dialogue:
        reasons.append("dialogue")
    if has_question:
        reasons.append("question")
    if has_exclaim:
        reasons.append("exclamation")
    if has_ellipsis:
        reasons.append("ellipsis")

    if has_ellipsis:
        return "suspense", reasons
    if has_dialogue:
        return "dialogue", reasons
    if has_question:
        return "question", reasons
    if has_exclaim:
        return "emphasis", reasons
    return "narration", reasons


def _pause_after_ms(text: str, *, style: str, paragraph_end: bool) -> int:
    stripped = text.rstrip()
    if ELLIPSIS_RE.search(stripped):
        pause = 1000
    elif re.search(r"\?[\u0022\u0027\u00bb\u201c\u201d]?$", stripped):
        pause = 520
    elif re.search(r"![\u0022\u0027\u00bb\u201c\u201d]?$", stripped):
        pause = 500
    elif re.search(r"[:;][\u0022\u0027\u00bb\u201c\u201d]?$", stripped):
        pause = 300
    elif re.search(r",[ \u0022\u0027\u00bb\u201c\u201d]*$", stripped):
        pause = 220
    else:
        pause = 420

    if style == "dialogue" and pause > 420:
        pause -= 60
    if paragraph_end:
        pause = max(pause, 820)
    return max(120, min(1600, pause))


def segment_text_for_prosody(text: str, *, language_code: str = "de") -> list[ProsodySegment]:
    segments: list[ProsodySegment] = []
    for paragraph in _paragraphs(text):
        sentence_texts = _sentences(paragraph, language_code=language_code)
        for index, sentence in enumerate(sentence_texts):
            if not sentence:
                continue
            paragraph_end = index == len(sentence_texts) - 1
            style, reasons = _style_for_sentence(sentence)
            if paragraph_end:
                reasons.append("paragraph_end")
            segments.append(
                ProsodySegment(
                    text=sentence,
                    style=style,
                    pause_after_ms=_pause_after_ms(sentence, style=style, paragraph_end=paragraph_end),
                    reasons=tuple(dict.fromkeys(reasons)),
                )
            )
    return segments


def _style_for_chunk(segments: list[ProsodySegment]) -> str:
    styles = Counter(segment.style for segment in segments)
    for style in ("suspense", "dialogue", "question", "emphasis"):
        if styles.get(style, 0):
            return style if len(styles) == 1 else f"mixed_{style}"
    return "narration"


def _reasons_for_chunk(
    segments: list[ProsodySegment],
    *,
    dense_score: int,
    forced_split: bool = False,
) -> tuple[str, ...]:
    reasons: list[str] = []
    for segment in segments:
        reasons.extend(segment.reasons)
    if dense_score > 0:
        reasons.append("name_markers")
    if forced_split:
        reasons.append("forced_split")
    return tuple(dict.fromkeys(reasons))


def _chunk_from_segments(
    segments: list[ProsodySegment],
    *,
    name_score: Callable[[str], int],
    forced_split: bool = False,
) -> ProsodyChunk:
    text = normalize_prosody_text(" ".join(segment.text for segment in segments))
    dense_score = name_score(text)
    return ProsodyChunk(
        text=text,
        style=_style_for_chunk(segments),
        pause_after_ms=segments[-1].pause_after_ms,
        reasons=_reasons_for_chunk(segments, dense_score=dense_score, forced_split=forced_split),
        segment_count=len(segments),
        name_marker_score=dense_score,
    )


def _style_for_merged_chunks(chunks: list[ProsodyChunk]) -> str:
    styles = Counter(chunk.style for chunk in chunks)
    for style in ("suspense", "dialogue", "question", "emphasis"):
        direct = styles.get(style, 0)
        mixed = sum(count for chunk_style, count in styles.items() if chunk_style == f"mixed_{style}")
        if direct or mixed:
            return style if len(styles) == 1 and not mixed else f"mixed_{style}"
    return "narration"


def _merge_chunk_group(chunks: list[ProsodyChunk], *, name_score: Callable[[str], int]) -> ProsodyChunk:
    text = normalize_prosody_text(" ".join(chunk.text for chunk in chunks))
    score = name_score(text)
    reasons: list[str] = []
    for chunk in chunks:
        reasons.extend(chunk.reasons)
    if len(chunks) > 1:
        reasons.append("short_chunk_merged")
    if score > 0:
        reasons.append("name_markers")
    return ProsodyChunk(
        text=text,
        style=_style_for_merged_chunks(chunks),
        pause_after_ms=chunks[-1].pause_after_ms,
        reasons=tuple(dict.fromkeys(reasons)),
        segment_count=sum(chunk.segment_count for chunk in chunks),
        name_marker_score=score,
    )


def _merge_short_chunks(
    chunks: list[ProsodyChunk],
    *,
    max_length: int,
    min_length: int,
    name_score: Callable[[str], int],
) -> list[ProsodyChunk]:
    if min_length <= 0 or not chunks:
        return chunks
    minimum = min(max(1, min_length), max_length)
    merged = list(chunks)
    index = 0
    while index < len(merged):
        chunk = merged[index]
        if len(chunk.text) >= minimum or len(merged) == 1:
            index += 1
            continue

        previous_candidate = None
        next_candidate = None
        if index > 0:
            previous_text = normalize_prosody_text(f"{merged[index - 1].text} {chunk.text}")
            if len(previous_text) <= max_length:
                previous_candidate = (len(previous_text), index - 1)
        if index + 1 < len(merged):
            next_text = normalize_prosody_text(f"{chunk.text} {merged[index + 1].text}")
            if len(next_text) <= max_length:
                next_candidate = (len(next_text), index + 1)

        if previous_candidate is None and next_candidate is None:
            index += 1
            continue

        use_previous = False
        if previous_candidate and next_candidate:
            # Prefer keeping clause tails with the sentence fragment that precedes them.
            use_previous = previous_candidate[0] <= next_candidate[0] or chunk.text.endswith((".", "!", "?"))
        elif previous_candidate:
            use_previous = True

        if use_previous:
            merged[index - 1 : index + 1] = [
                _merge_chunk_group([merged[index - 1], chunk], name_score=name_score)
            ]
            index = max(0, index - 1)
        else:
            merged[index : index + 2] = [
                _merge_chunk_group([chunk, merged[index + 1]], name_score=name_score)
            ]
    return merged


def _should_flush_before(current: list[ProsodySegment], next_segment: ProsodySegment, *, max_length: int) -> bool:
    if not current:
        return False
    current_text = normalize_prosody_text(" ".join(segment.text for segment in current))
    current_length = len(current_text)
    if current_length < min(60, max(35, max_length // 3)):
        return False
    previous = current[-1]
    paragraph_threshold = max(90, int(max_length * 0.90))
    strong_pause_threshold = max(80, int(max_length * 0.76))
    style_threshold = max(70, int(max_length * 0.66))
    if "paragraph_end" in previous.reasons and current_length >= paragraph_threshold:
        return True
    if previous.pause_after_ms >= 1000 and current_length >= strong_pause_threshold:
        return True
    current_dialogue = previous.style in {"dialogue", "suspense"}
    next_dialogue = next_segment.style in {"dialogue", "suspense"}
    if current_dialogue != next_dialogue and current_length >= style_threshold:
        return True
    if previous.style != next_segment.style and (previous.style != "narration" or next_segment.style != "narration"):
        return current_length >= max(85, int(max_length * 0.82))
    return False


def _split_oversized_segment(
    segment: ProsodySegment,
    max_length: int,
    *,
    name_score: Callable[[str], int],
) -> list[ProsodyChunk]:
    parts = split_text(segment.text, max_length)
    if not parts:
        return []
    chunks: list[ProsodyChunk] = []
    for index, part in enumerate(parts):
        split_segment = ProsodySegment(
            text=part,
            style=segment.style,
            pause_after_ms=segment.pause_after_ms if index == len(parts) - 1 else 180,
            reasons=segment.reasons if index == len(parts) - 1 else (*segment.reasons, "forced_split"),
        )
        chunks.append(_chunk_from_segments([split_segment], name_score=name_score, forced_split=index < len(parts) - 1))
    return chunks


def split_text_prosody_aware(
    text: str,
    max_length: int,
    *,
    dense_max_length: int = 0,
    is_dense: Callable[[str], bool] | None = None,
    name_score: Callable[[str], int] | None = None,
    dense_min_score: int = 1,
    min_length: int = 0,
    language_code: str = "de",
) -> list[ProsodyChunk]:
    if max_length <= 0:
        max_length = 1
    dense_limit = dense_max_length if 0 < dense_max_length < max_length else 0
    score_cache: dict[str, int] = {}
    dense_cache: dict[str, bool] = {}

    def score(value: str) -> int:
        key = value
        if key in score_cache:
            return score_cache[key]
        if name_score is not None:
            resolved = int(name_score(value))
        elif is_dense is not None and is_dense(value):
            resolved = 1
        else:
            resolved = 0
        score_cache[key] = resolved
        return resolved

    def dense(value: str) -> bool:
        key = value
        if key in dense_cache:
            return dense_cache[key]
        if name_score is not None:
            resolved = score(value) >= max(1, dense_min_score)
        elif is_dense is not None:
            resolved = bool(is_dense(value))
        else:
            resolved = score(value) > 0
        dense_cache[key] = resolved
        return resolved

    segments = segment_text_for_prosody(text, language_code=language_code)
    if not segments:
        return []

    chunks: list[ProsodyChunk] = []
    current: list[ProsodySegment] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        chunks.append(_chunk_from_segments(current, name_score=score))
        current = []

    for segment in segments:
        if len(segment.text) > max_length:
            flush()
            chunks.extend(_split_oversized_segment(segment, max_length, name_score=score))
            continue
        if not current:
            current = [segment]
            continue
        candidate_text = normalize_prosody_text(" ".join([*(item.text for item in current), segment.text]))
        exceeds_dense_target = dense_limit > 0 and len(candidate_text) > dense_limit and dense(candidate_text)
        if (
            len(candidate_text) > max_length
            or exceeds_dense_target
            or _should_flush_before(current, segment, max_length=max_length)
        ):
            flush()
            current = [segment]
        else:
            current.append(segment)
    flush()

    refined: list[ProsodyChunk] = []
    for chunk in chunks:
        if dense_limit > 0 and len(chunk.text) > dense_limit and dense(chunk.text):
            split_chunks = split_text_prosody_aware(
                chunk.text,
                dense_limit,
                dense_max_length=0,
                is_dense=is_dense,
                name_score=name_score,
                dense_min_score=dense_min_score,
                min_length=0,
                language_code=language_code,
            )
            refined.extend(split_chunks or [chunk])
        else:
            refined.append(chunk)
    return _merge_short_chunks(
        refined,
        max_length=max_length,
        min_length=min_length,
        name_score=score,
    )
