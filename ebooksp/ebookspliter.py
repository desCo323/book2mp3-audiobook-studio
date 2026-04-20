import os
import re
from ebooklib import epub
from bs4 import BeautifulSoup

# ================================
# Konfiguration
# ================================
# Wähle den Generierungsmodus:
# "chapter"  -> Es wird pro Kapitel eine TXT-Datei erstellt.
# "limit"    -> Es wird zusätzlich das Zeichenlimit (MAX_LENGTH) beachtet und in kleinere Blöcke gesplittet.
GENERATION_MODE = "limit"  # Alternativ "chapter"
MAX_LENGTH = 253

# ================================
# Funktionen zur Aufteilung
# ================================
def split_sentence_on_comma(sentence, max_length=MAX_LENGTH):
    """
    Versucht, einen langen Satz (länger als max_length) an einem Komma zu teilen.
    Wird ein Komma innerhalb der ersten max_length Zeichen gefunden, wird dort geteilt
    (das Komma bleibt am Ende des ersten Teils). Falls kein Komma gefunden wird,
    wird der Satz als Ganzes zurückgegeben.
    """
    sentence = sentence.strip()
    if len(sentence) <= max_length:
        return [sentence]
    
    # Suche nach dem letzten Komma in den ersten max_length Zeichen
    candidate = sentence[:max_length]
    pos = candidate.rfind(',')
    if pos == -1:
        # Kein Komma gefunden – also Rückgabe des ganzen Satzes (auch wenn er länger ist)
        return [sentence]
    
    # Erster Teil enthält das Komma
    first_part = sentence[:pos+1].strip()
    remainder = sentence[pos+1:].strip()
    
    result = []
    if first_part:
        result.append(first_part)
    if remainder:
        # Den Rest rekursiv prüfen
        result.extend(split_sentence_on_comma(remainder, max_length))
    return result

def pack_chunks(chunks, max_length=MAX_LENGTH):
    """
    Fügt die einzelnen Satz- (oder Teilsatz-)Fragmente zu Blöcken zusammen,
    die (wenn möglich) maximal max_length Zeichen lang sind. Falls ein einzelnes
    Fragment bereits länger ist, wird es als eigener Block belassen.
    """
    file_chunks = []
    current = ""
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        if current:
            # Mit einem Leerzeichen verbinden und prüfen, ob der Block noch passt
            if len(current) + 1 + len(chunk) <= max_length:
                current = current + " " + chunk
            else:
                file_chunks.append(current)
                # Ist das nächste Fragment selbst zu lang?
                if len(chunk) > max_length:
                    file_chunks.append(chunk)
                    current = ""
                else:
                    current = chunk
        else:
            if len(chunk) > max_length:
                file_chunks.append(chunk)
                current = ""
            else:
                current = chunk
    if current:
        file_chunks.append(current)
    return file_chunks

def split_text_into_chunks(text, max_length=MAX_LENGTH):
    """
    Zerlegt den gesamten Text in "File-Chunks", die möglichst nicht länger als
    max_length Zeichen sind. Zunächst wird der Text in Sätze aufgeteilt, und
    bei Sätzen, die zu lang sind, erfolgt ein Split an Kommas (sofern möglich).
    Anschließend werden die (Teil-)Sätze zu Blöcken zusammengefügt.
    """
    # Whitespace normalisieren (überzählige Leerzeichen und Zeilenumbrüche entfernen)
    text = re.sub(r'\s+', ' ', text).strip()
    # Text in Sätze unterteilen (Satzende: Punkt, Ausrufe- oder Fragezeichen)
    sentences = re.split(r'(?<=[.!?])\s+', text)
    sentences = [s.strip() for s in sentences if s.strip()]
    
    sentence_chunks = []
    for sentence in sentences:
        if len(sentence) > max_length:
            # Versuche, den Satz an einem Komma zu teilen
            parts = split_sentence_on_comma(sentence, max_length)
            sentence_chunks.extend(parts)
        else:
            sentence_chunks.append(sentence)
    
    # Satzfragmente zu Blöcken (File-Chunks) zusammenfügen
    file_chunks = pack_chunks(sentence_chunks, max_length)
    return file_chunks

# ================================
# EPUB-Verarbeitung
# ================================
def process_epub_file(epub_path, output_dir):
    """
    Liest ein EPUB ein, extrahiert pro Kapitel den reinen Text, entfernt leere Zeilen
    und speichert die Ausgabe in TXT-Dateien. Dabei wird entweder kapitelweise
    (GENERATION_MODE = "chapter") oder anhand des Zeichenlimits (GENERATION_MODE = "limit")
    vorgegangen.
    """
    try:
        book = epub.read_epub(epub_path)
    except Exception as e:
        print(f"Fehler beim Lesen von {epub_path}: {e}")
        return

    base_name = os.path.splitext(os.path.basename(epub_path))[0]
    
    # Kapitel ermitteln: zunächst über den Spine, alternativ alle HTML-Dokumente
    chapters = []
    for item_id, _ in book.spine:
        if item_id.lower() == "nav":
            continue
        item = book.get_item_with_id(item_id)
        if item is not None and isinstance(item, epub.EpubHtml):
            chapters.append(item)
    if not chapters:
        chapters = [item for item in book.get_items() if isinstance(item, epub.EpubHtml)]
    
    file_counter = 1
    for chapter in chapters:
        content = chapter.get_content()
        soup = BeautifulSoup(content, 'html.parser')
        text = soup.get_text(separator=" ")
        # Entferne leere Zeilen
        text = "\n".join(line for line in text.splitlines() if line.strip())
        
        if GENERATION_MODE == "chapter":
            # Kapitelweise: Ein gesamter Kapiteltext in eine Datei
            output_filename = os.path.join(output_dir, f"{base_name}_part{file_counter:02d}.txt")
            try:
                with open(output_filename, "w", encoding="utf-8") as f:
                    f.write(text)
                print(f"Geschrieben: {output_filename} (Länge: {len(text)})")
            except Exception as e:
                print(f"Fehler beim Schreiben von {output_filename}: {e}")
            file_counter += 1

        elif GENERATION_MODE == "limit":
            # Zeichenlimit: Text in Chunks (max. 253 Zeichen) aufteilen
            chunks = split_text_into_chunks(text, MAX_LENGTH)
            for chunk in chunks:
                output_filename = os.path.join(output_dir, f"{base_name}_part{file_counter:02d}.txt")
                try:
                    with open(output_filename, "w", encoding="utf-8") as f:
                        f.write(chunk)
                    print(f"Geschrieben: {output_filename} (Länge: {len(chunk)})")
                except Exception as e:
                    print(f"Fehler beim Schreiben von {output_filename}: {e}")
                file_counter += 1
        else:
            print("Ungültiger GENERATION_MODE. Bitte 'chapter' oder 'limit' verwenden.")

def process_all_epubs(input_dir, output_dir):
    """
    Durchläuft das Input-Verzeichnis, verarbeitet alle EPUB-Dateien und legt
    die resultierenden TXT-Dateien im Output-Verzeichnis ab.
    """
    os.makedirs(output_dir, exist_ok=True)
    for filename in os.listdir(input_dir):
        if filename.lower().endswith(".epub"):
            epub_path = os.path.join(input_dir, filename)
            print(f"\nVerarbeite Datei: {epub_path}")
            process_epub_file(epub_path, output_dir)

# ================================
# Hauptprogramm
# ================================
if __name__ == "__main__":
    # Verzeichnisse anpassen:
    input_directory = r"C:\Users\Seve\ebooksp\input"    # Hier liegen deine EPUB-Dateien
    output_directory = r"C:\Users\Seve\ebooksp\output"    # Hier werden die TXT-Dateien abgelegt

    process_all_epubs(input_directory, output_directory)
    print("\nAlle Dateien wurden verarbeitet.")
