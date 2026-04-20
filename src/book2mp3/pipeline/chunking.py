from __future__ import annotations

import re


def split_sentence_on_comma(sentence: str, max_length: int) -> list[str]:
    sentence = sentence.strip()
    if len(sentence) <= max_length:
        return [sentence]
    candidate = sentence[:max_length]
    comma_pos = candidate.rfind(",")
    if comma_pos == -1:
        return [sentence]
    first = sentence[: comma_pos + 1].strip()
    rest = sentence[comma_pos + 1 :].strip()
    chunks = [first] if first else []
    if rest:
        chunks.extend(split_sentence_on_comma(rest, max_length))
    return chunks


def pack_chunks(parts: list[str], max_length: int) -> list[str]:
    result: list[str] = []
    current = ""
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if not current:
            if len(part) > max_length:
                result.append(part)
            else:
                current = part
            continue
        candidate = f"{current} {part}"
        if len(candidate) <= max_length:
            current = candidate
            continue
        result.append(current)
        if len(part) > max_length:
            result.append(part)
            current = ""
        else:
            current = part
    if current:
        result.append(current)
    return result


def split_text(text: str, max_length: int) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", normalized) if s.strip()]
    sentence_parts: list[str] = []
    for sentence in sentences:
        if len(sentence) > max_length:
            sentence_parts.extend(split_sentence_on_comma(sentence, max_length))
        else:
            sentence_parts.append(sentence)
    return pack_chunks(sentence_parts, max_length)
