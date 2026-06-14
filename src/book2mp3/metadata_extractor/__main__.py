from __future__ import annotations

import argparse
import json
from pathlib import Path

from .evaluation import evaluate_metadata_extractor
from .extractor import extract_metadata_from_source
from .lexicon import (
    build_pronunciation_rules,
    load_global_lexicon,
    scan_books_for_lexicon,
    validate_global_lexicon,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m book2mp3.metadata_extractor")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract", help="Extract metadata from one source document")
    extract.add_argument("source_path")
    extract.add_argument("--offline", action="store_true", help="Disable online providers")
    extract.add_argument("--cache-path", default="")

    evaluate = sub.add_parser("evaluate", help="Evaluate the extractor against a corpus folder")
    evaluate.add_argument("root")
    evaluate.add_argument("--offline", action="store_true", help="Disable online providers")
    evaluate.add_argument("--suffix", action="append", default=[], help="Restrict evaluation to one or more suffixes, e.g. --suffix .epub")

    lexicon_validate = sub.add_parser("lexicon-validate", help="Validate the global author/character lexicon")
    lexicon_validate.add_argument("--path", default="")

    lexicon_scan = sub.add_parser("lexicon-scan", help="Check how well the lexicon matches a local book corpus")
    lexicon_scan.add_argument("root")
    lexicon_scan.add_argument("--path", default="")
    lexicon_scan.add_argument("--suffix", action="append", default=[], help="Restrict scan to one or more suffixes, e.g. --suffix .epub")

    lexicon_rules = sub.add_parser("lexicon-rules", help="Render XTTS pronunciation rules derived from the global lexicon")
    lexicon_rules.add_argument("--path", default="")
    lexicon_rules.add_argument("--author", action="append", default=[], help="Restrict rules to one or more authors")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "extract":
        cache_path = Path(args.cache_path).expanduser().resolve() if args.cache_path else None
        result = extract_metadata_from_source(
            args.source_path,
            allow_online=not args.offline,
            cache_path=cache_path,
        )
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
        return 0
    if args.command == "evaluate":
        suffixes = {suffix if suffix.startswith(".") else f".{suffix}" for suffix in args.suffix} or None
        summary = evaluate_metadata_extractor(
            Path(args.root).expanduser().resolve(),
            allow_online=not args.offline,
            suffixes=suffixes,
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0
    if args.command == "lexicon-validate":
        report = validate_global_lexicon(Path(args.path).expanduser().resolve() if args.path else None)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report.get("is_valid") else 1
    if args.command == "lexicon-scan":
        suffixes = {suffix if suffix.startswith(".") else f".{suffix}" for suffix in args.suffix} or None
        report = scan_books_for_lexicon(
            Path(args.root).expanduser().resolve(),
            path=(Path(args.path).expanduser().resolve() if args.path else None),
            suffixes=suffixes,
        )
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    if args.command == "lexicon-rules":
        lexicon = load_global_lexicon(Path(args.path).expanduser().resolve() if args.path else None)
        rules = build_pronunciation_rules(
            lexicon,
            authors={author.strip() for author in args.author if author.strip()} or None,
        )
        print(json.dumps(rules, indent=2, ensure_ascii=False))
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
