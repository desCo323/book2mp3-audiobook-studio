from __future__ import annotations

import re


CLAUSE_BOUNDARY_RE = re.compile(r"(?<=[,;:])\s+|(?<=\s[-–—])\s+")


def split_oversized_part(part: str, max_length: int) -> list[str]:
    part = part.strip()
    if not part:
        return []
    if len(part) <= max_length:
        return [part]

    for pattern in (r"[,;:]\s+", r"\s[-–—]\s+", r"\s+"):
        candidate = part[:max_length]
        matches = list(re.finditer(pattern, candidate))
        if not matches:
            continue
        split_at = matches[-1].end()
        head = part[:split_at].strip()
        tail = part[split_at:].strip()
        if head and tail:
            return [head, *split_oversized_part(tail, max_length)]
    return [part[:max_length].strip(), *split_oversized_part(part[max_length:].strip(), max_length)]


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
            clauses = [item.strip() for item in CLAUSE_BOUNDARY_RE.split(sentence) if item.strip()]
            if len(clauses) > 1:
                for clause in clauses:
                    sentence_parts.extend(split_oversized_part(clause, max_length))
            else:
                sentence_parts.extend(split_oversized_part(sentence, max_length))
        else:
            sentence_parts.append(sentence)
    return pack_chunks(sentence_parts, max_length)
