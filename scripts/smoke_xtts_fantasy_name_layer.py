from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from book2mp3.tts.pronunciation import (
    apply_pronunciation_rules,
    spoken_hint,
    suggest_document_pronunciation_rules,
)
from book2mp3.xtts_options import normalize_xtts_dialog_text


def main() -> int:
    expected_hints = {
        "Bayne": "Beyn",
        "Baynes": "Beyns",
        "Calondirs": "Kalondirs",
        "Constantine": "Konstantin",
        "Graydon": "Greydon",
        "Hugh": "Hju",
        "Irish Wolfhound": "Airisch Wolfhaund",
        "James": "Dschehms",
        "Johnny": "Dschonni",
        "Miguel": "Migel",
        "Quentin Caeravorn": "Kwentin Keravorn",
        "Wyr": "Wier",
    }
    for written, expected in expected_hints.items():
        actual = spoken_hint(written)
        if actual != expected:
            raise AssertionError(f"Expected spoken_hint({written!r})={expected!r}, got {actual!r}")

    source = (
        "Calondirs Rüstung glänzte, während Dragos’ Rücken im Licht lag. "
        "Quentin Caeravorn ritt auf dem Pegasus, Carling saß auf Runes Rücken. "
        "Bayne, Constantine und Graydon standen bei den Wyr. "
        "Eva, Miguel, Hugh, Andrea, Johnny und James sahen aus wie ein Irish Wolfhound."
    )
    rules = suggest_document_pronunciation_rules(source, limit=40, min_occurrences=1)
    by_match = {str(rule["match"]): str(rule["spoken_as"]) for rule in rules}
    for written, expected in expected_hints.items():
        if written == "Baynes":
            continue
        if " " in written and written != "Irish Wolfhound" and written != "Quentin Caeravorn":
            continue
        if written not in by_match:
            continue
        if by_match[written] != expected:
            raise AssertionError(f"Expected suggested rule {written}->{expected}, got {by_match[written]!r}")
    required_rules = {
        "Calondirs": "Kalondirs",
        "Constantine": "Konstantin",
        "Graydon": "Greydon",
        "Hugh": "Hju",
        "Johnny": "Dschonni",
        "Quentin": "Kwentin",
        "Wyr": "Wier",
    }
    for written, expected in required_rules.items():
        if by_match.get(written) != expected:
            raise AssertionError(f"Expected generated rule {written}->{expected}, got {by_match.get(written)!r}")
    forbidden_rules = {"Rüstung", "Rücken", "Körper", "Zähne", "Zügen", "Hälfte"}
    unexpected = sorted(forbidden_rules & set(by_match))
    if unexpected:
        raise AssertionError(f"Expected common German nouns to be filtered out, got: {unexpected}")

    transformed = apply_pronunciation_rules(source, rules)
    spoken_text = normalize_xtts_dialog_text(transformed.spoken_text)
    if "Dragos'" in spoken_text or "Dragos’" in spoken_text:
        raise AssertionError(f"Expected possessive apostrophe to be removed for XTTS: {spoken_text!r}")
    for expected in ("Kalondirs", "Kwentin", "Konstantin", "Greydon", "Wier", "Dschonni", "Dschehms"):
        if expected not in spoken_text:
            raise AssertionError(f"Expected {expected!r} in spoken XTTS text: {spoken_text!r}")
    print(
        {
            "rules": by_match,
            "spoken_text": spoken_text,
            "replacements": transformed.applied_occurrences,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
