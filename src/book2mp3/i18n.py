from __future__ import annotations

import locale
import os


SUPPORTED_UI_LANGUAGES = ("de", "en", "es", "pt")


def detect_system_language() -> str:
    candidates = [
        os.environ.get("LANG"),
        os.environ.get("LANGUAGE"),
        os.environ.get("LC_ALL"),
        locale.getlocale()[0],
        locale.getdefaultlocale()[0] if hasattr(locale, "getdefaultlocale") else None,
    ]
    for value in candidates:
        if value and ":" in value:
            value = value.split(":", 1)[0]
        normalized = normalize_ui_language(value or "")
        if normalized != "auto":
            return normalized
    return "en"


def normalize_ui_language(value: str | None) -> str:
    normalized = (value or "").strip().lower().replace("-", "_")
    if ":" in normalized:
        normalized = normalized.split(":", 1)[0]
    if not normalized or normalized == "auto":
        return "auto"
    if normalized in {"c", "posix", "c_utf8", "c.utf8"}:
        return "auto"
    if normalized.startswith("de"):
        return "de"
    if normalized.startswith("es"):
        return "es"
    if normalized.startswith("pt"):
        return "pt"
    if normalized.startswith("en"):
        return "en"
    return "en"


def resolve_ui_language(value: str | None) -> str:
    normalized = normalize_ui_language(value)
    if normalized == "auto":
        return detect_system_language()
    return normalized


def ui_language_choices(ui_language: str) -> list[tuple[str, str]]:
    labels = {
        "de": {
            "auto": "Automatisch (Systemsprache, sonst Englisch)",
            "en": "Englisch",
            "es": "Spanisch",
            "pt": "Portugiesisch",
            "de": "Deutsch",
        },
        "en": {
            "auto": "Automatic (system language, English fallback)",
            "en": "English",
            "es": "Spanish",
            "pt": "Portuguese",
            "de": "German",
        },
        "es": {
            "auto": "Automático (idioma del sistema, si no inglés)",
            "en": "Inglés",
            "es": "Español",
            "pt": "Portugués",
            "de": "Alemán",
        },
        "pt": {
            "auto": "Automático (idioma do sistema, senão inglês)",
            "en": "Inglês",
            "es": "Espanhol",
            "pt": "Português",
            "de": "Alemão",
        },
    }
    bundle = labels.get(ui_language, labels["en"])
    return [(code, bundle[code]) for code in ("auto", "en", "es", "pt", "de")]


def preferred_content_language_code(ui_language: str) -> str:
    return {
        "de": "de_DE",
        "en": "en_US",
        "es": "es_ES",
        "pt": "pt_BR",
    }.get(ui_language, "en_US")


KEY_TRANSLATIONS: dict[str, dict[str, str]] = {
    "status.language_changed": {
        "de": "Oberflächensprache gespeichert. Starte die App neu, damit alle Fenster konsistent umgeschaltet werden.",
        "en": "Interface language saved. Restart the app so every window switches consistently.",
        "es": "Idioma de la interfaz guardado. Reinicia la aplicación para que todas las ventanas cambien de forma coherente.",
        "pt": "Idioma da interface salvo. Reinicie o app para que todas as janelas mudem de forma consistente.",
    },
    "dialog.language_changed.title": {
        "de": "Sprache gespeichert",
        "en": "Language saved",
        "es": "Idioma guardado",
        "pt": "Idioma salvo",
    },
    "dialog.language_changed.body": {
        "de": "Die neue Oberflächensprache wurde gespeichert. Bitte starte die App neu, damit alle Dialoge und Menüs konsistent umgeschaltet werden.",
        "en": "The new interface language has been saved. Please restart the app so all dialogs and menus switch consistently.",
        "es": "El nuevo idioma de la interfaz se ha guardado. Reinicia la aplicación para que todos los diálogos y menús cambien correctamente.",
        "pt": "O novo idioma da interface foi salvo. Reinicie o aplicativo para que todos os diálogos e menus mudem corretamente.",
    },
    "queue.eta.learning": {
        "de": "ETA lernt noch",
        "en": "ETA learning",
        "es": "ETA aprendiendo",
        "pt": "ETA aprendendo",
    },
    "queue.eta.hours": {
        "de": "ETA ca. {hours:.1f} h",
        "en": "ETA approx. {hours:.1f} h",
        "es": "ETA aprox. {hours:.1f} h",
        "pt": "ETA aprox. {hours:.1f} h",
    },
    "queue.eta.minutes": {
        "de": "ETA ca. {minutes:.1f} min",
        "en": "ETA approx. {minutes:.1f} min",
        "es": "ETA aprox. {minutes:.1f} min",
        "pt": "ETA aprox. {minutes:.1f} min",
    },
    "settings.ui_language.hint": {
        "de": "Automatisch nutzt nach Möglichkeit die Sprache des Betriebssystems, sonst Englisch.",
        "en": "Automatic uses the operating system language when possible, otherwise English.",
        "es": "Automático usa el idioma del sistema operativo cuando sea posible; si no, inglés.",
        "pt": "Automático usa o idioma do sistema operacional quando possível; caso contrário, inglês.",
    },
    "settings.ui_language.label": {
        "de": "Oberflächensprache",
        "en": "Interface language",
        "es": "Idioma de la interfaz",
        "pt": "Idioma da interface",
    },
    "settings.ui_language.note": {
        "de": "Änderungen greifen nach einem Neustart der App vollständig.",
        "en": "Changes apply fully after restarting the app.",
        "es": "Los cambios se aplican completamente después de reiniciar la aplicación.",
        "pt": "As mudanças são aplicadas completamente após reiniciar o aplicativo.",
    },
    "source.analysis.idle": {
        "de": "Chapter detection is waiting for a source.",
        "en": "Chapter detection is waiting for a source.",
        "es": "La detección de capítulos está esperando una fuente.",
        "pt": "A detecção de capítulos está aguardando uma fonte.",
    },
    "source.analysis.supported": {
        "de": "Kapitel erkannt: {count} Kapitel können getrennt exportiert werden.",
        "en": "Chapters detected: {count} chapters can be exported separately.",
        "es": "Capítulos detectados: {count} capítulos pueden exportarse por separado.",
        "pt": "Capítulos detectados: {count} capítulos podem ser exportados separadamente.",
    },
    "source.analysis.unsupported": {
        "de": "Keine nutzbare Kapitelstruktur erkannt. Kapiteldateien bleiben deaktiviert.",
        "en": "No usable chapter structure detected. Chapter-per-file export stays disabled.",
        "es": "No se detectó una estructura de capítulos utilizable. La exportación por capítulo queda desactivada.",
        "pt": "Nenhuma estrutura de capítulos utilizável foi detectada. A exportação por capítulo permanece desativada.",
    },
    "source.analysis.error": {
        "de": "Kapitelanalyse fehlgeschlagen.",
        "en": "Chapter analysis failed.",
        "es": "La detección de capítulos falló.",
        "pt": "A análise de capítulos falhou.",
    },
    "source.analysis.multi": {
        "de": "{total} Quellen ausgewählt. {supported} Quelle(n) mit Kapitelstruktur, {fallback} Quelle(n) mit Fallback auf Einzeldatei.",
        "en": "{total} sources selected. {supported} source(s) support chapter export, {fallback} source(s) fall back to a single file.",
        "es": "{total} fuentes seleccionadas. {supported} fuente(s) admiten exportación por capítulos y {fallback} fuente(s) usan archivo único.",
        "pt": "{total} fontes selecionadas. {supported} fonte(s) suportam exportação por capítulos e {fallback} fonte(s) usam arquivo único.",
    },
    "source.count": {
        "de": "{total} Quelle(n) ausgewählt. {supported} davon unterstützen Kapiteldateien.",
        "en": "{total} source(s) selected. {supported} of them support chapter-per-file export.",
        "es": "{total} fuente(s) seleccionada(s). {supported} de ellas admiten exportación por capítulos.",
        "pt": "{total} fonte(s) selecionada(s). {supported} delas suportam exportação por capítulos.",
    },
    "source.count.none": {
        "de": "0 Quellen ausgewählt.",
        "en": "0 sources selected.",
        "es": "0 fuentes seleccionadas.",
        "pt": "0 fontes selecionadas.",
    },
    "output.chapter.enabled.single": {
        "de": "Kapiteldateien sind für diese Quelle freigeschaltet.",
        "en": "Chapter-per-file export is enabled for this source.",
        "es": "La exportación por capítulos está habilitada para esta fuente.",
        "pt": "A exportação por capítulos está habilitada para esta fonte.",
    },
    "output.chapter.enabled.multi": {
        "de": "Kapiteldateien sind für {supported}/{total} ausgewählte Quellen freigeschaltet.",
        "en": "Chapter-per-file export is enabled for {supported}/{total} selected sources.",
        "es": "La exportación por capítulos está habilitada para {supported}/{total} fuentes seleccionadas.",
        "pt": "A exportação por capítulos está habilitada para {supported}/{total} fontes selecionadas.",
    },
    "output.chapter.disabled": {
        "de": "Kapiteldateien bleiben deaktiviert, bis eine Quelle mit erkannten Kapiteln gewählt ist.",
        "en": "Chapter-per-file export stays disabled until you select a source with detected chapters.",
        "es": "La exportación por capítulos permanecerá desactivada hasta que selecciones una fuente con capítulos detectados.",
        "pt": "A exportação por capítulos permanecerá desativada até você selecionar uma fonte com capítulos detectados.",
    },
    "output.active_mode": {
        "de": "Aktive Auftragsausgabe: {mode}.",
        "en": "Active output for new jobs: {mode}.",
        "es": "Salida activa para nuevos trabajos: {mode}.",
        "pt": "Saída ativa para novos trabalhos: {mode}.",
    },
    "output.profile_fallback": {
        "de": "Das Profil würde standardmäßig {profile_mode} nutzen. Für diese Quelle wird auf {active_mode} zurückgefallen.",
        "en": "This profile would normally use {profile_mode}. For this source it falls back to {active_mode}.",
        "es": "Este perfil usaría normalmente {profile_mode}. Para esta fuente se aplica {active_mode}.",
        "pt": "Este perfil normalmente usaria {profile_mode}. Para esta fonte ele recua para {active_mode}.",
    },
    "output.choose_profile": {
        "de": "Wähle ein freigegebenes Produktionsprofil, um die finale Ausgabe zu übernehmen.",
        "en": "Choose an approved production profile to inherit the final output mode.",
        "es": "Elige un perfil de producción aprobado para heredar el modo de salida final.",
        "pt": "Escolha um perfil de produção aprovado para herdar o modo de saída final.",
    },
    "status.ready.queue": {
        "de": "Bereit. {count} Auftrag/Aufträge warten in der Queue und starten erst nach einem manuellen Start.",
        "en": "Ready. {count} job(s) are waiting in the queue and will start only after a manual start.",
        "es": "Listo. {count} trabajo(s) esperan en la cola y solo comenzarán después de un inicio manual.",
        "pt": "Pronto. {count} tarefa(s) estão na fila e só começarão após um início manual.",
    },
    "status.ready.blocked": {
        "de": "Bereit. {count} Auftrag/Aufträge sind blockiert und warten auf fehlende Runtime oder Profile.",
        "en": "Ready. {count} job(s) are blocked and waiting for missing runtime components or profiles.",
        "es": "Listo. {count} trabajo(s) están bloqueados y esperan componentes o perfiles faltantes.",
        "pt": "Pronto. {count} tarefa(s) estão bloqueadas aguardando componentes ou perfis ausentes.",
    },
    "status.ready.no_job": {
        "de": "Bereit. Noch kein Auftrag läuft.",
        "en": "Ready. No job is currently running.",
        "es": "Listo. No hay ningún trabajo en ejecución.",
        "pt": "Pronto. Nenhuma tarefa está em execução.",
    },
    "dialog.restart_required.title": {
        "de": "Neustart empfohlen",
        "en": "Restart recommended",
        "es": "Reinicio recomendado",
        "pt": "Reinício recomendado",
    },
    "dialog.restart_required.body": {
        "de": "Die Sprache wurde gespeichert. Bitte starte die App neu, damit alle Menüs, Dialoge und Statusmeldungen vollständig umgeschaltet werden.",
        "en": "The language has been saved. Please restart the app so all menus, dialogs, and status texts switch fully.",
        "es": "El idioma se ha guardado. Reinicia la aplicación para que todos los menús, diálogos y textos de estado cambien por completo.",
        "pt": "O idioma foi salvo. Reinicie o aplicativo para que todos os menus, diálogos e textos de status mudem completamente.",
    },
}


TEXT_TRANSLATIONS: dict[str, dict[str, str]] = {
    "book2mp3 Hörbuch-Studio": {
        "en": "book2mp3 Audiobook Studio",
        "es": "book2mp3 Estudio de Audiolibros",
        "pt": "book2mp3 Estúdio de Audiolivros",
    },
    "XTTS-Profilstudio": {
        "en": "XTTS Profile Studio",
        "es": "Estudio de perfiles XTTS",
        "pt": "Estúdio de perfis XTTS",
    },
    "XTTS optional einrichten": {
        "en": "Optional XTTS setup",
        "es": "Configuración opcional de XTTS",
        "pt": "Configuração opcional do XTTS",
    },
    "Profilstudio & Hörproben": {
        "en": "Profile Studio & Previews",
        "es": "Estudio de perfiles y pruebas",
        "pt": "Estúdio de perfis e prévias",
    },
    "Aufträge": {"en": "Jobs", "es": "Trabajos", "pt": "Tarefas"},
    "Warteschlange neu laden": {"en": "Reload queue", "es": "Recargar cola", "pt": "Recarregar fila"},
    "Ganz hoch": {"en": "Move to top", "es": "Mover arriba del todo", "pt": "Mover para o topo"},
    "Hoch": {"en": "Up", "es": "Subir", "pt": "Subir"},
    "Runter": {"en": "Down", "es": "Bajar", "pt": "Descer"},
    "Loeschen": {"en": "Delete", "es": "Eliminar", "pt": "Excluir"},
    "Quelle fehlt": {"en": "Missing source", "es": "Falta la fuente", "pt": "Fonte ausente"},
    "Kein Produktionsprofil": {"en": "No production profile", "es": "No hay perfil de producción", "pt": "Nenhum perfil de produção"},
    "Profil nicht freigegeben": {"en": "Profile not approved", "es": "Perfil no aprobado", "pt": "Perfil não aprovado"},
    "Keine Jobs erzeugt": {"en": "No jobs created", "es": "No se crearon trabajos", "pt": "Nenhuma tarefa criada"},
    "1. Auftrag anlegen": {"en": "1. Create jobs", "es": "1. Crear trabajos", "pt": "1. Criar tarefas"},
    "Buchquelle": {"en": "Source files", "es": "Archivos fuente", "pt": "Arquivos de origem"},
    "Dateien wählen": {"en": "Choose files", "es": "Elegir archivos", "pt": "Escolher arquivos"},
    "Leeren": {"en": "Clear", "es": "Limpiar", "pt": "Limpar"},
    "Noch keine Quelldateien ausgewählt.": {
        "en": "No source files selected yet.",
        "es": "Todavía no hay archivos fuente seleccionados.",
        "pt": "Nenhum arquivo de origem selecionado ainda.",
    },
    "Auswahl": {"en": "Selection", "es": "Selección", "pt": "Seleção"},
    "Kapitelerkennung": {"en": "Chapter detection", "es": "Detección de capítulos", "pt": "Detecção de capítulos"},
    "Importübersicht": {"en": "Import overview", "es": "Resumen de importación", "pt": "Resumo da importação"},
    "Produktionsprofil": {"en": "Production profile", "es": "Perfil de producción", "pt": "Perfil de produção"},
    "Metadaten & Tags": {"en": "Metadata & tags", "es": "Metadatos y etiquetas", "pt": "Metadados e tags"},
    "Titel": {"en": "Title", "es": "Título", "pt": "Título"},
    "Autor": {"en": "Author", "es": "Autor", "pt": "Autor"},
    "Sprecher": {"en": "Narrator", "es": "Narrador", "pt": "Narrador"},
    "Genre": {"en": "Genre", "es": "Género", "pt": "Gênero"},
    "Sprachtag": {"en": "Language tag", "es": "Etiqueta de idioma", "pt": "Tag de idioma"},
    "Kommentar": {"en": "Comment", "es": "Comentario", "pt": "Comentário"},
    "Freier Kommentar oder Quelle für die finalen MP3-Tags.": {
        "en": "Free comment or source note for the final MP3 tags.",
        "es": "Comentario libre o nota de origen para las etiquetas MP3 finales.",
        "pt": "Comentário livre ou nota de origem para as tags MP3 finais.",
    },
    "Aus Dateinamen vorschlagen": {"en": "Suggest from file name", "es": "Sugerir desde el nombre del archivo", "pt": "Sugerir a partir do nome do arquivo"},
    "Open Library suchen": {"en": "Search Open Library", "es": "Buscar en Open Library", "pt": "Pesquisar no Open Library"},
    "Besten Treffer übernehmen": {"en": "Apply best match", "es": "Aplicar mejor coincidencia", "pt": "Aplicar melhor resultado"},
    "Noch keine Metadaten geladen.": {"en": "No metadata loaded yet.", "es": "Todavía no se han cargado metadatos.", "pt": "Nenhum metadado carregado ainda."},
    "Treffer": {"en": "Matches", "es": "Coincidencias", "pt": "Correspondências"},
    "Gespeichertes Profil": {"en": "Saved profile", "es": "Perfil guardado", "pt": "Perfil salvo"},
    "Profile neu laden": {"en": "Reload profiles", "es": "Recargar perfiles", "pt": "Recarregar perfis"},
    "Zum Benchmark-Studio": {"en": "Open Benchmark Studio", "es": "Abrir estudio de benchmarks", "pt": "Abrir estúdio de benchmark"},
    "Profil-Info": {"en": "Profile info", "es": "Información del perfil", "pt": "Informações do perfil"},
    "Auftragsoptionen": {"en": "Job options", "es": "Opciones del trabajo", "pt": "Opções da tarefa"},
    "Priorität": {"en": "Priority", "es": "Prioridad", "pt": "Prioridade"},
    "Ausgabe-Hinweis": {"en": "Output note", "es": "Nota de salida", "pt": "Observação de saída"},
    "Eine große Enddatei": {"en": "One final file", "es": "Un archivo final", "pt": "Um arquivo final"},
    "Eine Datei pro Kapitel": {"en": "One file per chapter", "es": "Un archivo por capítulo", "pt": "Um arquivo por capítulo"},
    "Mehrere Dateien nach Zeit": {"en": "Multiple files by time", "es": "Varios archivos por tiempo", "pt": "Vários arquivos por tempo"},
    "Finale Ausgabe": {"en": "Final output", "es": "Salida final", "pt": "Saída final"},
    "Wird verwendet": {"en": "What will be used", "es": "Lo que se usará", "pt": "O que será usado"},
    "Aufträge aus Profil erzeugen": {"en": "Create jobs from profile", "es": "Crear trabajos desde el perfil", "pt": "Criar tarefas a partir do perfil"},
    "Ausgewählten Auftrag starten": {"en": "Start selected job", "es": "Iniciar trabajo seleccionado", "pt": "Iniciar tarefa selecionada"},
    "Ausgewählten Auftrag einreihen": {"en": "Queue selected job", "es": "Poner en cola el trabajo seleccionado", "pt": "Colocar a tarefa selecionada na fila"},
    "Aktuellen Auftrag stoppen": {"en": "Stop current job", "es": "Detener trabajo actual", "pt": "Parar tarefa atual"},
    "Auftrag": {"en": "New jobs", "es": "Nuevos trabajos", "pt": "Novas tarefas"},
    "2. Produktionsprofile": {"en": "2. Production profiles", "es": "2. Perfiles de producción", "pt": "2. Perfis de produção"},
    "Gespeicherte Produktionsprofile": {"en": "Saved production profiles", "es": "Perfiles de producción guardados", "pt": "Perfis de produção salvos"},
    "Im Auftragsdialog verwenden": {"en": "Use in job creator", "es": "Usar en el creador de trabajos", "pt": "Usar no criador de tarefas"},
    "Freigeben": {"en": "Approve", "es": "Aprobar", "pt": "Aprovar"},
    "Als getestet markieren": {"en": "Mark as tested", "es": "Marcar como probado", "pt": "Marcar como testado"},
    "Archivieren": {"en": "Archive", "es": "Archivar", "pt": "Arquivar"},
    "Produktionsprofile": {"en": "Production profiles", "es": "Perfiles de producción", "pt": "Perfis de produção"},
    "3. Benchmark-Studio": {"en": "3. Benchmark Studio", "es": "3. Estudio de benchmarks", "pt": "3. Estúdio de benchmark"},
    "Studio-Überblick": {"en": "Studio overview", "es": "Resumen del estudio", "pt": "Visão geral do estúdio"},
    "Überblick": {"en": "Overview", "es": "Resumen", "pt": "Visão geral"},
    "Hinweis": {"en": "Note", "es": "Nota", "pt": "Observação"},
    "Tests und Vergleich": {"en": "Tests and comparison", "es": "Pruebas y comparación", "pt": "Testes e comparação"},
    "Studio-Werkzeuge": {"en": "Studio tools", "es": "Herramientas del estudio", "pt": "Ferramentas do estúdio"},
    "Profilstudio": {"en": "Profile Studio", "es": "Estudio de perfiles", "pt": "Estúdio de perfis"},
    "Profil-Assistent": {"en": "Profile Assistant", "es": "Asistente de perfiles", "pt": "Assistente de perfis"},
    "Custom-Piper importieren": {"en": "Import custom Piper", "es": "Importar Piper personalizado", "pt": "Importar Piper personalizado"},
    "Stimmen neu laden": {"en": "Reload voices", "es": "Recargar voces", "pt": "Recarregar vozes"},
    "Benchmark-Studio": {"en": "Benchmark Studio", "es": "Estudio de benchmarks", "pt": "Estúdio de benchmark"},
    "4. XTTS-Profile": {"en": "4. XTTS Profiles", "es": "4. Perfiles XTTS", "pt": "4. Perfis XTTS"},
    "XTTS-Profile": {"en": "XTTS Profiles", "es": "Perfiles XTTS", "pt": "Perfis XTTS"},
    "XTTS-Runtime und Import": {"en": "XTTS runtime and import", "es": "Runtime e importación de XTTS", "pt": "Runtime e importação do XTTS"},
    "Schnellstart": {"en": "Quick start", "es": "Inicio rápido", "pt": "Início rápido"},
    "Bestand neu laden": {"en": "Reload inventory", "es": "Recargar inventario", "pt": "Recarregar inventário"},
    "XTTS jetzt einrichten": {"en": "Set up XTTS now", "es": "Configurar XTTS ahora", "pt": "Configurar XTTS agora"},
    "CUDA / XTTS prüfen": {"en": "Check CUDA / XTTS", "es": "Comprobar CUDA / XTTS", "pt": "Verificar CUDA / XTTS"},
    "XTTS-Profilstudio": {"en": "XTTS Profile Studio", "es": "Estudio de perfiles XTTS", "pt": "Estúdio de perfis XTTS"},
    "XTTS-Profile suchen": {"en": "Search XTTS profiles", "es": "Buscar perfiles XTTS", "pt": "Procurar perfis XTTS"},
    "Starterprofile laden": {"en": "Install starter profiles", "es": "Instalar perfiles iniciales", "pt": "Instalar perfis iniciais"},
    "Import": {"en": "Import", "es": "Importación", "pt": "Importação"},
    "Backend & Laufzeit": {"en": "Backend and runtime", "es": "Backend y runtime", "pt": "Backend e runtime"},
    "Einordnung": {"en": "Context", "es": "Contexto", "pt": "Contexto"},
    "Status": {"en": "Status", "es": "Estado", "pt": "Status"},
    "XTTS-Gerät": {"en": "XTTS device", "es": "Dispositivo XTTS", "pt": "Dispositivo XTTS"},
    "Runtime": {"en": "Runtime", "es": "Runtime", "pt": "Runtime"},
    "Piper-Stimmen": {"en": "Piper voices", "es": "Voces Piper", "pt": "Vozes Piper"},
    "Stimme": {"en": "Voice", "es": "Voz", "pt": "Voz"},
    "Sprache": {"en": "Language", "es": "Idioma", "pt": "Idioma"},
    "nur Frauenstimmen": {"en": "female voices only", "es": "solo voces femeninas", "pt": "apenas vozes femininas"},
    "nur high": {"en": "high only", "es": "solo high", "pt": "somente high"},
    "Filter": {"en": "Filters", "es": "Filtros", "pt": "Filtros"},
    "Profil": {"en": "Profile", "es": "Perfil", "pt": "Perfil"},
    "Verfügbare Profile": {"en": "Available profiles", "es": "Perfiles disponibles", "pt": "Perfis disponíveis"},
    "Importstatus": {"en": "Import status", "es": "Estado de importación", "pt": "Status da importação"},
    "Ausgewählt": {"en": "Selected", "es": "Seleccionado", "pt": "Selecionado"},
    "Referenz anhören": {"en": "Play reference", "es": "Escuchar referencia", "pt": "Ouvir referência"},
    "Profilordner öffnen": {"en": "Open profile folder", "es": "Abrir carpeta del perfil", "pt": "Abrir pasta do perfil"},
    "Produktionsprofil vorbereiten": {"en": "Prepare production profile", "es": "Preparar perfil de producción", "pt": "Preparar perfil de produção"},
    "Qualitäts-Preset": {"en": "Quality preset", "es": "Preajuste de calidad", "pt": "Preset de qualidade"},
    "Preset-Info": {"en": "Preset info", "es": "Información del preset", "pt": "Informações do preset"},
    "Ausgabe": {"en": "Output", "es": "Salida", "pt": "Saída"},
    "Eine Enddatei pro Kapitel": {"en": "One final file per chapter", "es": "Un archivo final por capítulo", "pt": "Um arquivo final por capítulo"},
    "Mehrere Enddateien nach Zeit": {"en": "Multiple final files by time", "es": "Varios archivos finales por tiempo", "pt": "Vários arquivos finais por tempo"},
    "Nur Segmentdateien behalten": {"en": "Keep segment files only", "es": "Conservar solo archivos de segmentos", "pt": "Manter apenas arquivos de segmentos"},
    "Teil-Länge": {"en": "Part length", "es": "Duración por parte", "pt": "Duração por parte"},
    "Zeichen pro Chunk": {"en": "Characters per chunk", "es": "Caracteres por fragmento", "pt": "Caracteres por bloco"},
    "Zwischen-WAV-Dateien behalten": {"en": "Keep intermediate WAV files", "es": "Conservar archivos WAV intermedios", "pt": "Manter arquivos WAV intermediários"},
    "Debug-Dateien": {"en": "Debug files", "es": "Archivos de depuración", "pt": "Arquivos de depuração"},
    "5. Aufträge": {"en": "5. Jobs", "es": "5. Trabajos", "pt": "5. Tarefas"},
    "Aktueller Auftrag": {"en": "Current job", "es": "Trabajo actual", "pt": "Tarefa atual"},
    "Jobordner öffnen": {"en": "Open job folder", "es": "Abrir carpeta del trabajo", "pt": "Abrir pasta da tarefa"},
    "Ausgabeordner öffnen": {"en": "Open output folder", "es": "Abrir carpeta de salida", "pt": "Abrir pasta de saída"},
    "Manifest öffnen": {"en": "Open manifest", "es": "Abrir manifiesto", "pt": "Abrir manifesto"},
    "Kapiteldatei öffnen": {"en": "Open chapters file", "es": "Abrir archivo de capítulos", "pt": "Abrir arquivo de capítulos"},
    "Stufen": {"en": "Stages", "es": "Fases", "pt": "Etapas"},
    "Kapitel": {"en": "Chapters", "es": "Capítulos", "pt": "Capítulos"},
    "Kapiteltext öffnen": {"en": "Open chapter text", "es": "Abrir texto del capítulo", "pt": "Abrir texto do capítulo"},
    "Kapitelaudio öffnen": {"en": "Open chapter audio", "es": "Abrir audio del capítulo", "pt": "Abrir áudio do capítulo"},
    "Kapitel erneut anstellen": {"en": "Retry chapter", "es": "Reintentar capítulo", "pt": "Reprocessar capítulo"},
    "Chunks": {"en": "Chunks", "es": "Fragmentos", "pt": "Blocos"},
    "Chunktext öffnen": {"en": "Open chunk text", "es": "Abrir texto del fragmento", "pt": "Abrir texto do bloco"},
    "Chunkaudio öffnen": {"en": "Open chunk audio", "es": "Abrir audio del fragmento", "pt": "Abrir áudio do bloco"},
    "Ausgewählte Chunks erneut anstellen": {"en": "Retry selected chunks", "es": "Reintentar fragmentos seleccionados", "pt": "Reprocessar blocos selecionados"},
    "Fehlgeschlagene Chunks erneut anstellen": {"en": "Retry failed chunks", "es": "Reintentar fragmentos fallidos", "pt": "Reprocessar blocos com falha"},
    "Gesamten Auftrag erneut anstellen": {"en": "Retry whole job", "es": "Reintentar todo el trabajo", "pt": "Reprocessar toda a tarefa"},
    "Auswahldetails": {"en": "Selection details", "es": "Detalles de la selección", "pt": "Detalhes da seleção"},
    "Logs": {"en": "Logs", "es": "Registros", "pt": "Logs"},
    "Queue & gespeicherte Vorschauen": {"en": "Queue and saved previews", "es": "Cola y previsualizaciones guardadas", "pt": "Fila e prévias salvas"},
    "Auftragsaktionen": {"en": "Job actions", "es": "Acciones del trabajo", "pt": "Ações da tarefa"},
    "Fertige Hörbücher": {"en": "Finished audiobooks", "es": "Audiolibros terminados", "pt": "Audiolivros concluídos"},
    "Hörbuch öffnen": {"en": "Open audiobook", "es": "Abrir audiolibro", "pt": "Abrir audiolivro"},
    "Ordner öffnen": {"en": "Open folder", "es": "Abrir carpeta", "pt": "Abrir pasta"},
    "Projekt löschen": {"en": "Delete project", "es": "Eliminar proyecto", "pt": "Excluir projeto"},
    "Nächsten Queue-Job starten": {"en": "Start next queued job", "es": "Iniciar el siguiente trabajo en cola", "pt": "Iniciar a próxima tarefa da fila"},
    "Priorität für Auswahl speichern": {"en": "Save priority for selection", "es": "Guardar prioridad de la selección", "pt": "Salvar prioridade da seleção"},
    "6. Diagnose": {"en": "6. Diagnostics", "es": "6. Diagnóstico", "pt": "6. Diagnóstico"},
    "Laufzeit- und Systemzustand": {"en": "Runtime and system status", "es": "Estado del runtime y del sistema", "pt": "Status do runtime e do sistema"},
    "Diagnose aktualisieren": {"en": "Refresh diagnostics", "es": "Actualizar diagnóstico", "pt": "Atualizar diagnóstico"},
    "XTTS optional einrichten": {"en": "Set up XTTS optionally", "es": "Configurar XTTS de forma opcional", "pt": "Configurar XTTS opcionalmente"},
    "Arbeitsbereich öffnen": {"en": "Open workspace", "es": "Abrir área de trabajo", "pt": "Abrir área de trabalho"},
    "Logs öffnen": {"en": "Open logs", "es": "Abrir logs", "pt": "Abrir logs"},
    "Appordner öffnen": {"en": "Open app folder", "es": "Abrir carpeta de la app", "pt": "Abrir pasta do app"},
    "Diagnose": {"en": "Diagnostics", "es": "Diagnóstico", "pt": "Diagnóstico"},
    "7. Einstellungen": {"en": "7. Settings", "es": "7. Ajustes", "pt": "7. Configurações"},
    "Einstellungen": {"en": "Settings", "es": "Ajustes", "pt": "Configurações"},
    "App-Zustand und Logging": {"en": "App state and logging", "es": "Estado de la app y logging", "pt": "Estado do app e logging"},
    "Sehr detailliertes Debug-Logging": {"en": "Very detailed debug logging", "es": "Logging de depuración muy detallado", "pt": "Logging de depuração muito detalhado"},
    "Logging": {"en": "Logging", "es": "Logging", "pt": "Logging"},
    "XTTS-Verarbeitung": {"en": "XTTS processing", "es": "Procesamiento XTTS", "pt": "Processamento XTTS"},
    "Automatisch entscheiden": {"en": "Choose automatically", "es": "Decidir automáticamente", "pt": "Decidir automaticamente"},
    "Immer seriell": {"en": "Always serial", "es": "Siempre en serie", "pt": "Sempre serial"},
    "Parallel CPU-Postprozess bevorzugen": {"en": "Prefer parallel CPU post-processing", "es": "Preferir postproceso paralelo en CPU", "pt": "Preferir pós-processamento paralelo na CPU"},
    "Modus-Hinweis": {"en": "Mode note", "es": "Nota del modo", "pt": "Observação do modo"},
    "App-Zustand zurücksetzen": {"en": "Reset app state", "es": "Restablecer estado de la app", "pt": "Redefinir estado do app"},
    "Arbeitsdateien": {"en": "Working files", "es": "Archivos de trabajo", "pt": "Arquivos de trabalho"},
    "App-Einstellungen": {"en": "App settings", "es": "Ajustes de la app", "pt": "Configurações do app"},
    "Profilordner": {"en": "Profiles folder", "es": "Carpeta de perfiles", "pt": "Pasta de perfis"},
    "App-Einstellungen öffnen": {"en": "Open app settings", "es": "Abrir ajustes de la app", "pt": "Abrir configurações do app"},
    "Profilstudio-Sessions öffnen": {"en": "Open studio sessions", "es": "Abrir sesiones del estudio", "pt": "Abrir sessões do estúdio"},
    "Hier erscheinen der Download- und Installationsfortschritt der optionalen XTTS-Runtime.": {
        "en": "Download and installation progress for the optional XTTS runtime appears here.",
        "es": "Aquí aparece el progreso de descarga e instalación del runtime opcional de XTTS.",
        "pt": "Aqui aparece o progresso de download e instalação do runtime opcional do XTTS.",
    },
    "XTTS jetzt einrichten": {"en": "Set up XTTS now", "es": "Configurar XTTS ahora", "pt": "Configurar XTTS agora"},
    "Runtime-Ordner öffnen": {"en": "Open runtime folder", "es": "Abrir carpeta del runtime", "pt": "Abrir pasta do runtime"},
    "Schließen": {"en": "Close", "es": "Cerrar", "pt": "Fechar"},
    "Profil anlegen oder importieren": {"en": "Create or import profile", "es": "Crear o importar perfil", "pt": "Criar ou importar perfil"},
    "Profilname": {"en": "Profile name", "es": "Nombre del perfil", "pt": "Nome do perfil"},
    "Zielsprache": {"en": "Target language", "es": "Idioma objetivo", "pt": "Idioma alvo"},
    "Samples hinzufuegen": {"en": "Add samples", "es": "Añadir muestras", "pt": "Adicionar amostras"},
    "Gefundene XTTS-Orte anzeigen": {"en": "Show found XTTS locations", "es": "Mostrar ubicaciones XTTS encontradas", "pt": "Mostrar locais XTTS encontrados"},
    "XTTS-Sprecher automatisch suchen": {"en": "Search XTTS speakers automatically", "es": "Buscar voces XTTS automáticamente", "pt": "Procurar vozes XTTS automaticamente"},
    "Starter-XTTS-Sprecher laden": {"en": "Install starter XTTS speakers", "es": "Instalar voces XTTS iniciales", "pt": "Instalar vozes XTTS iniciais"},
    "XTTS-WebUI-Sprecher importieren": {"en": "Import XTTS-WebUI speakers", "es": "Importar voces de XTTS-WebUI", "pt": "Importar vozes do XTTS-WebUI"},
    "Samples leeren": {"en": "Clear samples", "es": "Limpiar muestras", "pt": "Limpar amostras"},
    "Notizen, Zielstimme, Aufnahmeumgebung, Stil, Besonderheiten.": {
        "en": "Notes, target voice, recording environment, style, special notes.",
        "es": "Notas, voz objetivo, entorno de grabación, estilo y detalles especiales.",
        "pt": "Notas, voz alvo, ambiente de gravação, estilo e detalhes especiais.",
    },
    "Profil speichern": {"en": "Save profile", "es": "Guardar perfil", "pt": "Salvar perfil"},
    "Vorhandene XTTS-Profile": {"en": "Existing XTTS profiles", "es": "Perfiles XTTS existentes", "pt": "Perfis XTTS existentes"},
    "Ausgewaehltes Sample hoeren": {"en": "Listen to selected sample", "es": "Escuchar la muestra seleccionada", "pt": "Ouvir a amostra selecionada"},
    "Profilordner oeffnen": {"en": "Open profile folder", "es": "Abrir carpeta del perfil", "pt": "Abrir pasta do perfil"},
    "Quelle und aktueller Ausschnitt": {"en": "Source and current excerpt", "es": "Fuente y fragmento actual", "pt": "Fonte e trecho atual"},
    "Keine Quelle gewaehlt": {"en": "No source selected", "es": "No se ha seleccionado ninguna fuente", "pt": "Nenhuma fonte selecionada"},
    "Buch waehlen": {"en": "Choose book", "es": "Elegir libro", "pt": "Escolher livro"},
    "Neue Stelle": {"en": "New excerpt", "es": "Nuevo fragmento", "pt": "Novo trecho"},
    "Hier erscheint automatisch eine zufaellige Stelle aus dem Buch.": {
        "en": "A random excerpt from the book appears here automatically.",
        "es": "Aquí aparece automáticamente un fragmento aleatorio del libro.",
        "pt": "Um trecho aleatório do livro aparece aqui automaticamente.",
    },
    "Preview": {"en": "Preview", "es": "Vista previa", "pt": "Prévia"},
    "Noch keine Preview gerendert.": {"en": "No preview rendered yet.", "es": "Aún no se ha renderizado ninguna vista previa.", "pt": "Nenhuma prévia foi renderizada ainda."},
}


def tr(ui_language: str, key: str, **kwargs) -> str:
    bundle = KEY_TRANSLATIONS.get(key, {})
    text = bundle.get(ui_language) or bundle.get("en") or key
    return text.format(**kwargs)


def translate_text(text: str, ui_language: str) -> str:
    if ui_language == "de":
        return text
    bundle = TEXT_TRANSLATIONS.get(text)
    if not bundle:
        return text
    return bundle.get(ui_language) or bundle.get("en") or text


def apply_text(text: str, ui_language: str) -> str:
    return translate_text(text, ui_language)


def translate_widget_tree(widget, ui_language: str) -> None:
    from PySide6.QtWidgets import (
        QCheckBox,
        QDialog,
        QGroupBox,
        QLabel,
        QLineEdit,
        QMainWindow,
        QPlainTextEdit,
        QPushButton,
        QRadioButton,
        QTabWidget,
        QWidget,
        QComboBox,
    )

    if isinstance(widget, (QDialog, QMainWindow, QWidget)) and widget.windowTitle():
        widget.setWindowTitle(translate_text(widget.windowTitle(), ui_language))
    if isinstance(widget, QLabel):
        widget.setText(translate_text(widget.text(), ui_language))
    elif isinstance(widget, QPushButton):
        widget.setText(translate_text(widget.text(), ui_language))
        if widget.toolTip():
            widget.setToolTip(translate_text(widget.toolTip(), ui_language))
    elif isinstance(widget, QCheckBox):
        widget.setText(translate_text(widget.text(), ui_language))
    elif isinstance(widget, QRadioButton):
        widget.setText(translate_text(widget.text(), ui_language))
        if widget.toolTip():
            widget.setToolTip(translate_text(widget.toolTip(), ui_language))
    elif isinstance(widget, QGroupBox):
        widget.setTitle(translate_text(widget.title(), ui_language))
    elif isinstance(widget, QLineEdit):
        if widget.placeholderText():
            widget.setPlaceholderText(translate_text(widget.placeholderText(), ui_language))
    elif isinstance(widget, QPlainTextEdit):
        if widget.placeholderText():
            widget.setPlaceholderText(translate_text(widget.placeholderText(), ui_language))
    elif isinstance(widget, QTabWidget):
        for index in range(widget.count()):
            widget.setTabText(index, translate_text(widget.tabText(index), ui_language))
    elif isinstance(widget, QComboBox):
        for index in range(widget.count()):
            widget.setItemText(index, translate_text(widget.itemText(index), ui_language))

    for child in widget.findChildren(QWidget):
        if child is widget:
            continue
        if getattr(child, "_book2mp3_i18n_done", False):
            continue
        child._book2mp3_i18n_done = True
        translate_widget_tree(child, ui_language)
