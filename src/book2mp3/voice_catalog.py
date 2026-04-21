from __future__ import annotations

from dataclasses import dataclass


LANGUAGE_LABELS = {
    "de_DE": "Deutsch",
    "es_AR": "Espanol (AR)",
    "en_GB": "English (UK)",
    "en_US": "English (US)",
    "fr_FR": "Francais",
    "es_ES": "Espanol (ES)",
    "es_MX": "Espanol (MX)",
    "it_IT": "Italiano",
    "nl_NL": "Nederlands",
    "nl_BE": "Nederlands (BE)",
    "pt_BR": "Portugues (BR)",
    "fi_FI": "Suomi",
    "cs_CZ": "Cestina",
    "da_DK": "Dansk",
    "sv_SE": "Svenska",
    "pl_PL": "Polski",
    "tr_TR": "Turkce",
    "ro_RO": "Romana",
}

VOICE_NOTES = {
    "en_US-lessac-high": "female",
    "en_US-ljspeech-high": "female",
    "en_GB-cori-high": "female",
    "es_AR-daniela-high": "female",
    "en_US-amy-medium": "female",
    "en_GB-jenny_dioco-medium": "female",
    "fr_FR-siwis-medium": "female",
    "sv_SE-lisa-medium": "female",
}

PREFERRED_VOICE_ORDER = [
    "en_US-ljspeech-high",
    "en_US-lessac-high",
    "en_GB-cori-high",
    "es_AR-daniela-high",
    "de_DE-thorsten_emotional-medium",
    "de_DE-thorsten-high",
    "de_DE-mls-medium",
    "de_DE-kerstin-low",
    "en_US-libritts-high",
    "en_US-amy-medium",
    "en_US-ryan-high",
    "en_GB-jenny_dioco-medium",
    "en_GB-alba-medium",
    "fr_FR-siwis-medium",
    "fr_FR-mls-medium",
    "es_ES-sharvard-medium",
    "es_MX-claude-high",
    "it_IT-riccardo-x_low",
    "nl_NL-mls-medium",
    "nl_NL-pim-medium",
    "pt_BR-faber-medium",
    "pt_BR-cadu-medium",
    "fi_FI-harri-medium",
    "cs_CZ-jirka-medium",
    "da_DK-talesyntese-medium",
    "sv_SE-lisa-medium",
    "pl_PL-gosia-medium",
    "tr_TR-fahrettin-medium",
    "ro_RO-mihai-medium",
]

DEFAULT_VOICE_PACK = [
    "en_US-ljspeech-high",
    "en_US-lessac-high",
    "en_GB-cori-high",
    "es_AR-daniela-high",
    "de_DE-thorsten_emotional-medium",
    "de_DE-thorsten-high",
    "de_DE-mls-medium",
    "de_DE-kerstin-low",
    "en_US-libritts-high",
    "en_US-amy-medium",
    "en_US-ryan-high",
    "en_GB-jenny_dioco-medium",
    "en_GB-alba-medium",
    "fr_FR-siwis-medium",
    "fr_FR-mls-medium",
    "es_ES-sharvard-medium",
    "es_MX-claude-high",
    "it_IT-riccardo-x_low",
    "nl_NL-mls-medium",
    "nl_NL-pim-medium",
    "pt_BR-faber-medium",
    "pt_BR-cadu-medium",
    "fi_FI-harri-medium",
    "cs_CZ-jirka-medium",
    "da_DK-talesyntese-medium",
    "sv_SE-lisa-medium",
    "pl_PL-gosia-medium",
    "tr_TR-fahrettin-medium",
    "ro_RO-mihai-medium",
]


def voice_language_code(voice_id: str) -> str:
    return voice_id.split("-", 1)[0]


def voice_language_label(voice_id: str) -> str:
    return LANGUAGE_LABELS.get(voice_language_code(voice_id), voice_language_code(voice_id))


def voice_quality(voice_id: str) -> str:
    return voice_id.rsplit("-", 1)[-1]


def voice_name(voice_id: str) -> str:
    parts = voice_id.split("-", 2)
    return parts[1] if len(parts) > 1 else voice_id


def voice_note(voice_id: str) -> str:
    return VOICE_NOTES.get(voice_id, "")


def is_female_voice(voice_id: str) -> bool:
    return voice_note(voice_id) == "female"


def format_voice_label(voice_id: str) -> str:
    note = voice_note(voice_id)
    if note:
        return f"{voice_language_label(voice_id)} | {voice_name(voice_id)} | {voice_quality(voice_id)} | {note}"
    return f"{voice_language_label(voice_id)} | {voice_name(voice_id)} | {voice_quality(voice_id)}"


def language_choices(voice_ids: list[str]) -> list[tuple[str, str]]:
    languages = sorted({voice_language_code(voice_id) for voice_id in voice_ids})
    return [("", "Alle Sprachen")] + [(code, voice_language_label(code)) for code in languages]


def sort_voice_ids(voice_ids: list[str]) -> list[str]:
    seen: list[str] = []
    ordered = [voice_id for voice_id in PREFERRED_VOICE_ORDER if voice_id in voice_ids]
    seen.extend(ordered)
    remaining = sorted(
        [voice_id for voice_id in voice_ids if voice_id not in seen],
        key=lambda item: (
            voice_language_label(item),
            0 if voice_quality(item) == "high" else 1 if voice_quality(item) == "medium" else 2,
            voice_name(item),
            item,
        ),
    )
    return ordered + remaining


def filter_voice_ids(
    voice_ids: list[str],
    language_code: str,
    *,
    female_only: bool = False,
    high_only: bool = False,
) -> list[str]:
    filtered = list(voice_ids)
    if language_code:
        filtered = [voice_id for voice_id in filtered if voice_language_code(voice_id) == language_code]
    if female_only:
        filtered = [voice_id for voice_id in filtered if is_female_voice(voice_id)]
    if high_only:
        filtered = [voice_id for voice_id in filtered if voice_quality(voice_id) == "high"]
    return sort_voice_ids(filtered)


def voice_filter_empty_message(language_code: str, *, female_only: bool = False, high_only: bool = False) -> str:
    if language_code == "de_DE" and female_only and high_only:
        return (
            "Keine deutsche weibliche Piper-Stimme in high verfuegbar. "
            "Nimm XTTS fuer natuerliche deutsche Frauenstimmen oder entferne den high-Filter."
        )
    if female_only and high_only:
        return "Keine weibliche high-Piper-Stimme fuer diesen Filter gefunden"
    if female_only:
        return "Keine Frauenstimme fuer diesen Filter gefunden"
    if high_only:
        return "Keine high-Piper-Stimme fuer diesen Filter gefunden"
    return "Keine Stimme fuer diesen Filter gefunden"
