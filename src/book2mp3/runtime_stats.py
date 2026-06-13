from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from book2mp3.models import utc_now

MAX_HISTORY_ENTRIES = 600


def _default_payload() -> dict[str, Any]:
    return {
        "updated_at": "",
        "entries": [],
    }


def load_runtime_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _default_payload()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return _default_payload()
    if not isinstance(payload, dict):
        return _default_payload()
    entries = payload.get("entries")
    if not isinstance(entries, list):
        payload["entries"] = []
    payload.setdefault("updated_at", "")
    return payload


def save_runtime_stats(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = utc_now()
    payload["entries"] = list(payload.get("entries", []))[-MAX_HISTORY_ENTRIES:]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def record_runtime_stat(path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    payload = load_runtime_stats(path)
    entries = list(payload.get("entries", []))
    entries.append(entry)
    payload["entries"] = entries[-MAX_HISTORY_ENTRIES:]
    save_runtime_stats(path, payload)
    return payload


def _matching_entries(
    entries: list[dict[str, Any]],
    *,
    backend: str,
    saved_profile_id: str,
    voice_id: str,
    voice_profile_id: str,
    device_mode: str,
    output_mode: str,
) -> list[dict[str, Any]]:
    relevant = [
        entry
        for entry in entries
        if entry.get("backend") == backend
        and entry.get("device_mode") == device_mode
        and entry.get("output_mode") == output_mode
        and entry.get("total_duration_seconds", 0) > 0
    ]
    if not relevant:
        return []
    if saved_profile_id:
        exact = [entry for entry in relevant if entry.get("saved_profile_id") == saved_profile_id]
        if exact:
            return exact
    if voice_profile_id:
        exact = [entry for entry in relevant if entry.get("voice_profile_id") == voice_profile_id]
        if exact:
            return exact
    if voice_id:
        exact = [entry for entry in relevant if entry.get("voice_id") == voice_id]
        if exact:
            return exact
    return relevant


def _average_seconds_per_char(entries: list[dict[str, Any]]) -> float | None:
    total_chars = sum(max(0, int(entry.get("source_characters", 0) or 0)) for entry in entries)
    total_seconds = sum(max(0.0, float(entry.get("total_duration_seconds", 0) or 0.0)) for entry in entries)
    if total_chars <= 0 or total_seconds <= 0:
        return None
    return total_seconds / total_chars


def estimate_runtime(
    path: Path,
    *,
    backend: str,
    saved_profile_id: str,
    voice_id: str,
    voice_profile_id: str,
    device_mode: str,
    processing_mode: str,
    output_mode: str,
    source_characters: int,
    chunk_count: int,
) -> dict[str, Any]:
    payload = load_runtime_stats(path)
    entries = _matching_entries(
        list(payload.get("entries", [])),
        backend=backend,
        saved_profile_id=saved_profile_id,
        voice_id=voice_id,
        voice_profile_id=voice_profile_id,
        device_mode=device_mode,
        output_mode=output_mode,
    )
    mode_entries = [entry for entry in entries if entry.get("processing_mode") == processing_mode]
    if not mode_entries:
        mode_entries = entries
    sample_count = len(mode_entries)
    if not mode_entries:
        return {
            "estimated_total_seconds": 0.0,
            "estimated_remaining_seconds": 0.0,
            "confidence": "none",
            "sample_count": 0,
        }
    seconds_per_char = _average_seconds_per_char(mode_entries)
    if seconds_per_char is not None and source_characters > 0:
        estimated_total = seconds_per_char * source_characters
    else:
        durations = [float(entry.get("total_duration_seconds", 0) or 0.0) for entry in mode_entries]
        estimated_total = sum(durations) / len(durations) if durations else 0.0
    if chunk_count > 0:
        chunk_rates = [
            float(entry.get("total_duration_seconds", 0) or 0.0) / max(1, int(entry.get("chunk_count", 0) or 0))
            for entry in mode_entries
            if int(entry.get("chunk_count", 0) or 0) > 0
        ]
        if chunk_rates:
            chunk_estimate = (sum(chunk_rates) / len(chunk_rates)) * chunk_count
            if estimated_total > 0:
                estimated_total = (estimated_total * 0.7) + (chunk_estimate * 0.3)
            else:
                estimated_total = chunk_estimate
    confidence = "low"
    if sample_count >= 6:
        confidence = "high"
    elif sample_count >= 3:
        confidence = "medium"
    return {
        "estimated_total_seconds": round(max(0.0, estimated_total), 3),
        "estimated_remaining_seconds": round(max(0.0, estimated_total), 3),
        "confidence": confidence,
        "sample_count": sample_count,
    }


def preferred_processing_mode(
    path: Path,
    *,
    backend: str,
    saved_profile_id: str,
    voice_id: str,
    voice_profile_id: str,
    device_mode: str,
    output_mode: str,
) -> dict[str, Any]:
    payload = load_runtime_stats(path)
    entries = _matching_entries(
        list(payload.get("entries", [])),
        backend=backend,
        saved_profile_id=saved_profile_id,
        voice_id=voice_id,
        voice_profile_id=voice_profile_id,
        device_mode=device_mode,
        output_mode=output_mode,
    )
    if not entries:
        return {"mode": "", "reason": "Noch keine Laufzeitdaten vorhanden.", "sample_count": 0}
    by_mode: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        by_mode.setdefault(str(entry.get("processing_mode", "serial")), []).append(entry)
    scored: list[tuple[str, float, int]] = []
    for mode, mode_entries in by_mode.items():
        seconds_per_char = _average_seconds_per_char(mode_entries)
        if seconds_per_char is None:
            durations = [float(entry.get("total_duration_seconds", 0) or 0.0) for entry in mode_entries]
            if not durations:
                continue
            score = sum(durations) / len(durations)
        else:
            score = seconds_per_char
        scored.append((mode, score, len(mode_entries)))
    if not scored:
        return {"mode": "", "reason": "Keine brauchbaren Laufzeitwerte gefunden.", "sample_count": len(entries)}
    scored.sort(key=lambda item: item[1])
    best_mode, _, best_count = scored[0]
    if len(scored) > 1:
        second_mode, second_score, _ = scored[1]
        best_score = scored[0][1]
        if best_score > 0 and ((second_score - best_score) / best_score) < 0.05:
            return {
                "mode": best_mode if best_count >= 3 else "",
                "reason": "Parallel und seriell liegen noch zu dicht beieinander.",
                "sample_count": len(entries),
            }
        return {
            "mode": best_mode if best_count >= 2 else "",
            "reason": f"{best_mode} ist derzeit schneller als {second_mode}.",
            "sample_count": len(entries),
        }
    return {
        "mode": best_mode if best_count >= 3 else "",
        "reason": f"{best_mode} ist der bisher einzige ausreichend gemessene Modus.",
        "sample_count": len(entries),
    }


def runtime_statistics_summary(path: Path) -> dict[str, Any]:
    payload = load_runtime_stats(path)
    entries = list(payload.get("entries", []))
    mode_counts: dict[str, int] = {}
    backend_counts: dict[str, int] = {}
    total_durations = [
        float(entry.get("total_duration_seconds", 0) or 0.0)
        for entry in entries
        if float(entry.get("total_duration_seconds", 0) or 0.0) > 0
    ]
    for entry in entries:
        mode = str(entry.get("processing_mode", "unknown") or "unknown")
        backend = str(entry.get("backend", "unknown") or "unknown")
        mode_counts[mode] = mode_counts.get(mode, 0) + 1
        backend_counts[backend] = backend_counts.get(backend, 0) + 1
    return {
        "entry_count": len(entries),
        "updated_at": payload.get("updated_at", ""),
        "mode_counts": mode_counts,
        "backend_counts": backend_counts,
        "average_total_seconds": round(sum(total_durations) / len(total_durations), 3) if total_durations else 0.0,
        "recent_entries": entries[-5:],
    }
