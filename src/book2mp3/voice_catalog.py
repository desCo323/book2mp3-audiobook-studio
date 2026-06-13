from __future__ import annotations

from dataclasses import dataclass

from book2mp3.i18n import resolve_ui_language

LANGUAGE_LABELS = {
    "de": {
        "de_DE": "Deutsch",
        "es_AR": "Spanisch (AR)",
        "en_GB": "Englisch (UK)",
        "en_US": "Englisch (US)",
        "fr_FR": "Französisch",
        "es_ES": "Spanisch (ES)",
        "es_MX": "Spanisch (MX)",
        "it_IT": "Italienisch",
        "nl_NL": "Niederländisch",
        "nl_BE": "Niederländisch (BE)",
        "pt_BR": "Portugiesisch (BR)",
        "pt_PT": "Portugiesisch (PT)",
        "fi_FI": "Finnisch",
        "cs_CZ": "Tschechisch",
        "da_DK": "Dänisch",
        "sv_SE": "Schwedisch",
        "pl_PL": "Polnisch",
        "tr_TR": "Türkisch",
        "ro_RO": "Rumänisch",
    },
    "en": {
        "de_DE": "German",
        "es_AR": "Spanish (AR)",
        "en_GB": "English (UK)",
        "en_US": "English (US)",
        "fr_FR": "French",
        "es_ES": "Spanish (ES)",
        "es_MX": "Spanish (MX)",
        "it_IT": "Italian",
        "nl_NL": "Dutch",
        "nl_BE": "Dutch (BE)",
        "pt_BR": "Portuguese (BR)",
        "pt_PT": "Portuguese (PT)",
        "fi_FI": "Finnish",
        "cs_CZ": "Czech",
        "da_DK": "Danish",
        "sv_SE": "Swedish",
        "pl_PL": "Polish",
        "tr_TR": "Turkish",
        "ro_RO": "Romanian",
    },
    "es": {
        "de_DE": "Alemán",
        "es_AR": "Español (AR)",
        "en_GB": "Inglés (UK)",
        "en_US": "Inglés (US)",
        "fr_FR": "Francés",
        "es_ES": "Español (ES)",
        "es_MX": "Español (MX)",
        "it_IT": "Italiano",
        "nl_NL": "Neerlandés",
        "nl_BE": "Neerlandés (BE)",
        "pt_BR": "Portugués (BR)",
        "pt_PT": "Portugués (PT)",
        "fi_FI": "Finés",
        "cs_CZ": "Checo",
        "da_DK": "Danés",
        "sv_SE": "Sueco",
        "pl_PL": "Polaco",
        "tr_TR": "Turco",
        "ro_RO": "Rumano",
    },
    "pt": {
        "de_DE": "Alemão",
        "es_AR": "Espanhol (AR)",
        "en_GB": "Inglês (UK)",
        "en_US": "Inglês (US)",
        "fr_FR": "Francês",
        "es_ES": "Espanhol (ES)",
        "es_MX": "Espanhol (MX)",
        "it_IT": "Italiano",
        "nl_NL": "Holandês",
        "nl_BE": "Holandês (BE)",
        "pt_BR": "Português (BR)",
        "pt_PT": "Português (PT)",
        "fi_FI": "Finlandês",
        "cs_CZ": "Tcheco",
        "da_DK": "Dinamarquês",
        "sv_SE": "Sueco",
        "pl_PL": "Polonês",
        "tr_TR": "Turco",
        "ro_RO": "Romeno",
    },
}

VOICE_NOTES = {
    "de_DE-eva_k-x_low": "female",
    "de_DE-kerstin-low": "female",
    "de_DE-ramona-low": "female",
    "en_US-amy-low": "female",
    "en_US-lessac-high": "female",
    "en_US-lessac-medium": "female",
    "en_US-lessac-low": "female",
    "en_US-ljspeech-high": "female",
    "en_US-ljspeech-medium": "female",
    "en_US-hfc_female-medium": "female",
    "en_US-kathleen-low": "female",
    "en_US-kristin-medium": "female",
    "en_GB-cori-high": "female",
    "en_GB-cori-medium": "female",
    "en_GB-alba-medium": "female",
    "en_GB-southern_english_female-low": "female",
    "es_AR-daniela-high": "female",
    "en_US-amy-medium": "female",
    "en_GB-jenny_dioco-medium": "female",
    "fr_FR-siwis-low": "female",
    "fr_FR-siwis-medium": "female",
    "it_IT-paola-medium": "female",
    "sv_SE-lisa-medium": "female",
}

PREFERRED_VOICE_ORDER = [
    "de_DE-ramona-low",
    "de_DE-kerstin-low",
    "de_DE-eva_k-x_low",
    "en_US-ljspeech-high",
    "en_US-ljspeech-medium",
    "en_US-lessac-high",
    "en_US-lessac-medium",
    "en_US-hfc_female-medium",
    "en_US-kristin-medium",
    "en_US-kathleen-low",
    "en_GB-cori-high",
    "en_GB-cori-medium",
    "en_GB-alba-medium",
    "en_GB-jenny_dioco-medium",
    "en_GB-southern_english_female-low",
    "es_AR-daniela-high",
    "fr_FR-siwis-medium",
    "fr_FR-siwis-low",
    "de_DE-thorsten_emotional-medium",
    "de_DE-thorsten-high",
    "de_DE-mls-medium",
    "en_US-libritts-high",
    "en_US-amy-medium",
    "en_US-ryan-high",
    "fr_FR-mls-medium",
    "es_ES-sharvard-medium",
    "es_MX-claude-high",
    "es_ES-davefx-medium",
    "it_IT-paola-medium",
    "it_IT-riccardo-x_low",
    "nl_NL-mls-medium",
    "nl_NL-pim-medium",
    "pt_BR-faber-medium",
    "pt_BR-cadu-medium",
    "pt_BR-jeff-medium",
    "pt_BR-edresson-low",
    "pt_PT-tugao-medium",
    "fi_FI-harri-medium",
    "cs_CZ-jirka-medium",
    "da_DK-talesyntese-medium",
    "sv_SE-lisa-medium",
    "pl_PL-gosia-medium",
    "tr_TR-fahrettin-medium",
    "ro_RO-mihai-medium",
]

DEFAULT_VOICE_PACK = [
    "de_DE-eva_k-x_low",
    "de_DE-ramona-low",
    "en_US-ljspeech-high",
    "en_US-ljspeech-medium",
    "en_US-lessac-high",
    "en_US-lessac-medium",
    "en_US-hfc_female-medium",
    "en_US-kristin-medium",
    "en_GB-cori-high",
    "en_GB-cori-medium",
    "en_GB-alba-medium",
    "en_GB-jenny_dioco-medium",
    "en_GB-southern_english_female-low",
    "es_AR-daniela-high",
    "de_DE-thorsten_emotional-medium",
    "de_DE-thorsten-high",
    "de_DE-mls-medium",
    "de_DE-kerstin-low",
    "en_US-libritts-high",
    "en_US-amy-medium",
    "en_US-ryan-high",
    "fr_FR-siwis-medium",
    "fr_FR-siwis-low",
    "fr_FR-mls-medium",
    "es_ES-sharvard-medium",
    "es_MX-claude-high",
    "es_ES-davefx-medium",
    "it_IT-paola-medium",
    "it_IT-riccardo-x_low",
    "nl_NL-mls-medium",
    "nl_NL-pim-medium",
    "pt_BR-faber-medium",
    "pt_BR-cadu-medium",
    "pt_BR-jeff-medium",
    "pt_BR-edresson-low",
    "pt_PT-tugao-medium",
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


def voice_language_label(voice_id: str, *, ui_language: str = "en") -> str:
    code = voice_language_code(voice_id)
    bundle = LANGUAGE_LABELS.get(resolve_ui_language(ui_language), LANGUAGE_LABELS["en"])
    return bundle.get(code, code)


def voice_quality(voice_id: str) -> str:
    return voice_id.rsplit("-", 1)[-1]


def voice_name(voice_id: str) -> str:
    parts = voice_id.split("-", 2)
    return parts[1] if len(parts) > 1 else voice_id


def voice_note(voice_id: str) -> str:
    return VOICE_NOTES.get(voice_id, "")


def is_female_voice(voice_id: str) -> bool:
    return voice_note(voice_id) == "female"


def format_voice_label(voice_id: str, *, ui_language: str = "en") -> str:
    note = voice_note(voice_id)
    if note:
        return f"{voice_language_label(voice_id, ui_language=ui_language)} | {voice_name(voice_id)} | {voice_quality(voice_id)} | {note}"
    return f"{voice_language_label(voice_id, ui_language=ui_language)} | {voice_name(voice_id)} | {voice_quality(voice_id)}"

def language_choices(voice_ids: list[str], *, ui_language: str = "en") -> list[tuple[str, str]]:
    languages = sorted({voice_language_code(voice_id) for voice_id in voice_ids})
    all_label = {
        "de": "Alle Sprachen",
        "en": "All languages",
        "es": "Todos los idiomas",
        "pt": "Todos os idiomas",
    }.get(resolve_ui_language(ui_language), "All languages")
    return [("", all_label)] + [(code, voice_language_label(code, ui_language=ui_language)) for code in languages]


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


def voice_filter_empty_message(language_code: str, *, ui_language: str = "en", female_only: bool = False, high_only: bool = False) -> str:
    lang = resolve_ui_language(ui_language)
    if language_code == "de_DE" and female_only and high_only:
        if lang == "de":
            return (
                "Keine deutsche weibliche Piper-Stimme in high verfügbar. "
                "Nimm XTTS für natürlichere deutsche Frauenstimmen oder entferne den high-Filter."
            )
        if lang == "es":
            return "No hay una voz Piper femenina alemana en high. Usa XTTS para voces femeninas alemanas más naturales o quita el filtro high."
        if lang == "pt":
            return "Não existe uma voz Piper feminina alemã em high. Use XTTS para vozes femininas alemãs mais naturais ou remova o filtro high."
        return "No German female Piper voice is available in high quality. Use XTTS for more natural German female voices or remove the high filter."
    if female_only and high_only:
        return {
            "de": "Keine weibliche high-Piper-Stimme für diesen Filter gefunden",
            "es": "No se encontró una voz Piper femenina high para este filtro",
            "pt": "Nenhuma voz Piper feminina high foi encontrada para este filtro",
        }.get(lang, "No female high-quality Piper voice was found for this filter")
    if female_only:
        return {
            "de": "Keine Frauenstimme für diesen Filter gefunden",
            "es": "No se encontró una voz femenina para este filtro",
            "pt": "Nenhuma voz feminina foi encontrada para este filtro",
        }.get(lang, "No female voice was found for this filter")
    if high_only:
        return {
            "de": "Keine high-Piper-Stimme für diesen Filter gefunden",
            "es": "No se encontró una voz Piper high para este filtro",
            "pt": "Nenhuma voz Piper high foi encontrada para este filtro",
        }.get(lang, "No high-quality Piper voice was found for this filter")
    return {
        "de": "Keine Stimme für diesen Filter gefunden",
        "es": "No se encontró ninguna voz para este filtro",
        "pt": "Nenhuma voz foi encontrada para este filtro",
    }.get(lang, "No voice was found for this filter")
