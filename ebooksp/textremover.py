import os
import re

# Verzeichnisse festlegen
text_dir = r"C:\Users\Seve\ebooksp\aufgang"
wav_dir = r"F:\xtts-webui-v1_0-portable\webui\output\batch_20250212_105447"

# Regex-Muster definieren
# Für Textdateien erwartet man z.B. "Name_partNummer"
pattern_text = re.compile(r'^(.*?)_part(\d+)$', re.IGNORECASE)
# Für WAV-Dateien: Der Dateiname beginnt mit einem Namen, gefolgt von _partNummer und optional einem Suffix wie _output...
pattern_wav = re.compile(r'^(.*?)_part(\d+)(?:_output.*)?$', re.IGNORECASE)

# Alle WAV-Dateien durchsuchen und (Name, Part)-Tupel sammeln
wav_tuples = set()
for wav_file in os.listdir(wav_dir):
    if wav_file.lower().endswith('.wav'):
        base_wav = os.path.splitext(wav_file)[0]
        match_wav = pattern_wav.match(base_wav)
        if match_wav:
            name_wav = match_wav.group(1)
            part_wav = match_wav.group(2)
            wav_tuples.add((name_wav, part_wav))

deleted_count = 0
remaining_count = 0

# Textdateien verarbeiten
for text_file in os.listdir(text_dir):
    text_path = os.path.join(text_dir, text_file)
    if os.path.isfile(text_path):
        base_text = os.path.splitext(text_file)[0]
        match_text = pattern_text.match(base_text)
        if match_text:
            name_text = match_text.group(1)
            part_text = match_text.group(2)
            # Prüfen, ob ein passendes WAV existiert (Name und Part stimmen überein)
            if (name_text, part_text) in wav_tuples:
                print(f"Lösche {text_path}")
                os.remove(text_path)
                deleted_count += 1
            else:
                remaining_count += 1
        else:
            # Dateien, die nicht dem Muster entsprechen, werden als übrig gezählt
            remaining_count += 1

print(f"Dateien gelöscht: {deleted_count}")
print(f"Dateien übrig: {remaining_count}")
