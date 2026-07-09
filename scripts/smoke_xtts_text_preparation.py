from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from book2mp3.pipeline.chunking import split_text
from book2mp3.tts.pronunciation import apply_pronunciation_rules
from book2mp3.xtts_options import normalize_xtts_dialog_text, safe_xtts_chunk_chars
from scripts.render_xtts_dialogue_example import _variant_pronunciation_rules


def main() -> int:
    source = (
        "« »Wirst du uns überhaupt nicht vermissen?« Talwyn sackte ein wenig in sich zusammen. "
        "»Darum geht es nicht, und das weißt du auch.« "
        "Izzy stand unter dem Baum. Hinter ihr warteten Éibhear und Rhi. "
        "»Na los!« »Wohin?«, fragte Talan."
    )
    rules = [
        {"match": "Talwyn", "spoken_as": "Talwin", "scope": "whole_phrase", "enabled": True},
        {"match": "Éibhear", "spoken_as": "Eber", "scope": "whole_phrase", "enabled": True},
        {"match": "Rhi", "spoken_as": "Ri", "scope": "whole_phrase", "enabled": True},
        {"match": "Izzy", "spoken_as": "Issi", "scope": "whole_phrase", "enabled": True},
    ]
    transformed = apply_pronunciation_rules(source, rules)
    spoken_text = normalize_xtts_dialog_text(transformed.spoken_text)
    if "«" in spoken_text or "»" in spoken_text:
        raise AssertionError(f"Expected dialogue quotes to be removed, got: {spoken_text!r}")
    for expected in ("Talwin", "Eber", "Ri", "Issi", "Wohin?"):
        if expected not in spoken_text:
            raise AssertionError(f"Expected {expected!r} in prepared XTTS text: {spoken_text!r}")
    max_chars = safe_xtts_chunk_chars(100, "de")
    chunks = split_text(spoken_text, max_chars)
    if len(chunks) < 2:
        raise AssertionError(f"Expected multi-chunk prepared XTTS text, got: {chunks!r}")
    oversized = [chunk for chunk in chunks if len(chunk) > max_chars]
    if oversized:
        raise AssertionError(f"Expected chunks <= {max_chars}, got: {oversized!r}")
    override_rules = _variant_pronunciation_rules(
        rules,
        [
            {"match": "Talwyn", "spoken_as": "Tallwin", "scope": "whole_phrase", "enabled": True},
            {"match": "Éibhear", "spoken_as": "Eiwer", "scope": "whole_phrase", "enabled": True},
        ],
    )
    override_text = normalize_xtts_dialog_text(apply_pronunciation_rules(source, override_rules).spoken_text)
    for expected in ("Tallwin", "Eiwer"):
        if expected not in override_text:
            raise AssertionError(f"Expected override {expected!r} in prepared XTTS text: {override_text!r}")
    for replaced in ("Talwin", "Eber"):
        if replaced in override_text:
            raise AssertionError(f"Expected old rule {replaced!r} to be replaced: {override_text!r}")
    print(
        {
            "source_chars": len(source),
            "spoken_chars": len(spoken_text),
            "chunk_count": len(chunks),
            "chunk_lengths": [len(chunk) for chunk in chunks],
            "replacements": transformed.applied_occurrences,
            "override_text": override_text,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
