import os
import re
from pydub import AudioSegment

# Konfiguration: Eingangs- und Ausgangsverzeichnis sowie Dateiname der zusammengefügten Datei
OUTPUT_DIR=  r"F:\xtts-webui-v1_0-portable\webui\output\mp3komb"     # Pfad zum Verzeichnis, in dem die WAV-Dateien liegen
INPUT_DIR = r"F:\xtts-webui-v1_0-portable\webui\output\batch_20250204_194523"  # Pfad zum Verzeichnis, in dem die MP3-Datei gespeichert wird
OUTPUT_FILENAME = "combined_output.mp3"  # Name der zusammengefügten MP3-Datei

def get_files(directory):
    """
    Sucht im angegebenen Verzeichnis nach WAV-Dateien, die irgendwo im Dateinamen das Muster 'partXXX'
    enthalten, wobei XXX die Dateinummer ist.
    """
    # Regex: beliebiger Text, dann 'part', gefolgt von einer oder mehreren Ziffern, beliebiger Text und .wav
    pattern = re.compile(r'.*part(\d+).*\.wav$', re.IGNORECASE)
    files = []
    for filename in os.listdir(directory):
        match = pattern.match(filename)
        if match:
            part_num = int(match.group(1))
            files.append((part_num, filename))
    return files

def check_sequence(sorted_files):
    """
    Überprüft, ob die sortierte Liste der Dateien eine lückenlose Sequenz bildet.
    Gibt eine Fehlermeldung aus, falls Teile fehlen.
    """
    if not sorted_files:
        print("Keine passenden Dateien gefunden.")
        return False

    expected = sorted_files[0][0]
    for part, filename in sorted_files:
        if part != expected:
            print(f"Fehler: Fehlender Teil! Erwartet: {expected}, gefunden: {part} in Datei '{filename}'")
            return False
        expected += 1
    return True

def combine_audio_files(input_dir, sorted_files, output_filepath):
    """
    Fügt die WAV-Dateien in der richtigen Reihenfolge zusammen und exportiert sie als MP3.
    """
    combined = AudioSegment.empty()

    for part, filename in sorted_files:
        filepath = os.path.join(input_dir, filename)
        try:
            audio = AudioSegment.from_wav(filepath)
            combined += audio
            print(f"Teil {part} ({filename}) wurde hinzugefügt.")
        except Exception as e:
            print(f"Fehler beim Laden der Datei '{filename}': {e}")
            return False

    try:
        combined.export(output_filepath, format="mp3")
        print(f"Zusammenführung abgeschlossen: {output_filepath}")
        return True
    except Exception as e:
        print(f"Fehler beim Exportieren der zusammengefügten Datei: {e}")
        return False

def main():
    # Sicherstellen, dass das Ausgangsverzeichnis existiert
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Ausgabeverzeichnis '{OUTPUT_DIR}' wurde erstellt.")

    # Dateien aus dem Eingangsverzeichnis suchen und Liste erstellen
    files = get_files(INPUT_DIR)
    if not files:
        print("Es wurden keine passenden WAV-Dateien gefunden.")
        return

    # Sortieren nach der extrahierten Part-Nummer
    sorted_files = sorted(files, key=lambda x: x[0])
    print("Gefundene Dateien (sortiert):")
    for part, filename in sorted_files:
        print(f"  Part {part}: {filename}")

    # Sequenz überprüfen
    if not check_sequence(sorted_files):
        print("Die Sequenz der Dateien ist nicht vollständig. Abbruch.")
        return

    # Vollständigen Pfad zur Ausgabedatei erstellen
    output_filepath = os.path.join(OUTPUT_DIR, OUTPUT_FILENAME)

    # Dateien zusammenfügen
    combine_audio_files(INPUT_DIR, sorted_files, output_filepath)

if __name__ == "__main__":
    main()
