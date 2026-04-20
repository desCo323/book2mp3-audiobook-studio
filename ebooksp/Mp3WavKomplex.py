import os
import re
import subprocess
from pydub import AudioSegment

# --- Konfiguration ---
OUTPUT_DIR=  r"F:\NEXTCLOUDE\Documents\FECLOUD\EBOOKS\mp3audiobook"     # Pfad zum Verzeichnis, in dem die WAV-Dateien liegen
INPUT_DIR = r"F:\xtts-webui-v1_0-portable\webui\output\fertig"
MAX_SEGMENT_DURATION_MS = 1800000  # Maximale Dauer eines Zwischenstücks in Millisekunden (hier 30 Minuten)

def sanitize_filename(name):
    """
    Entfernt problematische Zeichen aus Dateinamen und trimmt Leerzeichen.
    """
    return re.sub(r'[<>:"/\\|?*]', '_', name).strip(" _")

def get_grouped_files(directory):
    """
    Durchsucht das Verzeichnis (rekursiv) nach WAV-Dateien, die das Muster 'partXXX' enthalten.
    Gruppiert sie anhand des Teils des Namens vor 'part'.
    """
    pattern = re.compile(r'^(.*?)part(\d+).*\.wav$', re.IGNORECASE)
    grouped_files = {}
    for root, dirs, files in os.walk(directory):
        for filename in files:
            if not filename.lower().endswith('.wav'):
                continue
            match = pattern.match(filename)
            if match:
                group_key = match.group(1).strip()
                part_number = int(match.group(2))
                full_path = os.path.join(root, filename)
                grouped_files.setdefault(group_key, []).append((part_number, full_path, filename))
    return grouped_files

def check_sequence(sorted_files):
    """
    Überprüft, ob in der sortierten Liste der Dateien die Part-Nummern lückenlos fortlaufen.
    """
    if not sorted_files:
        return False
    expected = sorted_files[0][0]
    for part, filepath, filename in sorted_files:
        if part != expected:
            print(f"Fehler: In '{filename}' fehlt ein Teil. Erwartet: {expected}, gefunden: {part}")
            return False
        expected += 1
    return True

def process_group(group_key, sorted_files, output_dir):
    """
    Verarbeitet eine Gruppe:
      - Fügt die WAV-Dateien schrittweise zusammen.
      - Exportiert immer dann ein Zwischenstück als MP3, wenn die akkumulierte Dauer MAX_SEGMENT_DURATION_MS überschreitet.
      - Werden mehrere Zwischenstücke erzeugt, so werden diese mittels ffmpeg zusammengeführt.
    """
    sanitized_group = sanitize_filename(group_key)
    if not sanitized_group:
        sanitized_group = "output"
    
    intermediate_files = []
    combined = AudioSegment.empty()
    chunk_index = 1

    # Durchlaufe die WAV-Dateien der Gruppe in sortierter Reihenfolge
    for part, filepath, filename in sorted_files:
        try:
            audio = AudioSegment.from_wav(filepath)
        except Exception as e:
            print(f"Fehler beim Laden der Datei '{filename}': {e}")
            return False
        combined += audio
        # Sobald die akkumulierte Dauer den Schwellwert überschreitet, exportiere das aktuelle Segment
        if len(combined) >= MAX_SEGMENT_DURATION_MS:
            chunk_filename = f"{sanitized_group}_chunk{chunk_index}.mp3"
            chunk_filepath = os.path.join(output_dir, chunk_filename)
            try:
                combined.export(chunk_filepath, format="mp3", codec="libmp3lame")
                print(f"Exportiert: {chunk_filename} (Dauer: {len(combined)} ms)")
                intermediate_files.append(chunk_filepath)
            except Exception as e:
                print(f"Fehler beim Exportieren von {chunk_filename}: {e}")
                return False
            chunk_index += 1
            combined = AudioSegment.empty()
    # Exportiere das Reststück, falls vorhanden
    if len(combined) > 0:
        chunk_filename = f"{sanitized_group}_chunk{chunk_index}.mp3"
        chunk_filepath = os.path.join(output_dir, chunk_filename)
        try:
            combined.export(chunk_filepath, format="mp3", codec="libmp3lame")
            print(f"Exportiert: {chunk_filename} (Dauer: {len(combined)} ms)")
            intermediate_files.append(chunk_filepath)
        except Exception as e:
            print(f"Fehler beim Exportieren von {chunk_filename}: {e}")
            return False

    final_output_filepath = os.path.join(output_dir, f"{sanitized_group}.mp3")
    if len(intermediate_files) == 0:
        print("Keine Audio-Chunks exportiert.")
        return False
    elif len(intermediate_files) == 1:
        # Nur ein Chunk vorhanden – umbenennen als finale Datei
        try:
            os.rename(intermediate_files[0], final_output_filepath)
            print(f"Finale Datei erstellt: {final_output_filepath}")
        except Exception as e:
            print(f"Fehler beim Umbenennen der Datei: {e}")
            return False
    else:
        # Mehrere Zwischenstücke: Diese werden mit ffmpeg zusammengeführt.
        list_filename = os.path.join(output_dir, f"{sanitized_group}_concat_list.txt")
        try:
            with open(list_filename, "w", encoding="utf-8") as f:
                for chunk in intermediate_files:
                    f.write(f"file '{os.path.abspath(chunk)}'\n")
            cmd = [
                "ffmpeg",
                "-f", "concat",
                "-safe", "0",
                "-i", list_filename,
                "-c", "copy",
                final_output_filepath
            ]
            subprocess.run(cmd, check=True)
            print(f"Finale Datei erstellt: {final_output_filepath}")
        except Exception as e:
            print(f"Fehler beim Zusammenführen der Zwischenstücke: {e}")
            return False
        finally:
            # Aufräumen: Zwischenstücke und die temporäre Liste löschen
            if os.path.exists(list_filename):
                os.remove(list_filename)
            for chunk in intermediate_files:
                if os.path.exists(chunk):
                    os.remove(chunk)
    return True

def main():
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Ausgabeverzeichnis '{OUTPUT_DIR}' wurde erstellt.")
    
    groups = get_grouped_files(INPUT_DIR)
    if not groups:
        print("Es wurden keine passenden WAV-Dateien gefunden.")
        return
    
    # Für jede Gruppe: sortieren, Sequenz prüfen und verarbeiten
    for group_key, files in groups.items():
        print(f"\nVerarbeite Gruppe: '{group_key}'")
        sorted_files = sorted(files, key=lambda x: x[0])
        for part, filepath, filename in sorted_files:
            print(f"  Part {part}: {filename}")
        
        if not check_sequence(sorted_files):
            print(f"Sequenzfehler in Gruppe '{group_key}'. Diese Gruppe wird übersprungen.")
            continue
        
        if not process_group(group_key, sorted_files, OUTPUT_DIR):
            print(f"Fehler bei der Verarbeitung der Gruppe '{group_key}'.")

if __name__ == "__main__":
    main()