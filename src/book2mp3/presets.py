from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QualityPreset:
    preset_id: str
    label: str
    description: str
    max_chars: int
    output_mode: str
    keep_wav: bool
    sentence_silence: float
    length_scale: float


QUALITY_PRESETS = [
    QualityPreset(
        preset_id="fast_cpu",
        label="Schnell",
        description="Kleinere Chunks, segmentierte Ausgabe, zuegig fuer CPU-Systeme.",
        max_chars=160,
        output_mode="segments",
        keep_wav=False,
        sentence_silence=0.12,
        length_scale=0.95,
    ),
    QualityPreset(
        preset_id="balanced",
        label="Balanciert",
        description="Robuste Standardeinstellung fuer normale Hoerbuecher.",
        max_chars=220,
        output_mode="segments",
        keep_wav=False,
        sentence_silence=0.20,
        length_scale=1.0,
    ),
    QualityPreset(
        preset_id="natural",
        label="Natuerlich",
        description="Mehr Ruhe und etwas langsamere Prosodie fuer natuerlicheres Vorlesen.",
        max_chars=260,
        output_mode="single_file",
        keep_wav=False,
        sentence_silence=0.30,
        length_scale=1.06,
    ),
    QualityPreset(
        preset_id="premium_natural",
        label="Premium Natuerlich",
        description="Empfohlener XTTS-Pfad fuer natuerlichere Hoerbuchausgabe mit Sprecherprofilen.",
        max_chars=280,
        output_mode="single_file",
        keep_wav=False,
        sentence_silence=0.24,
        length_scale=1.0,
    ),
]


PRESETS_BY_ID = {preset.preset_id: preset for preset in QUALITY_PRESETS}


def get_preset(preset_id: str) -> QualityPreset:
    return PRESETS_BY_ID.get(preset_id, PRESETS_BY_ID["balanced"])
