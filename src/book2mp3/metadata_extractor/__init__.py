from __future__ import annotations

from .extractor import BookMetadataExtractor, extract_metadata_from_source, guess_metadata_from_filename
from .lexicon import (
    build_author_pronunciation_rules,
    build_pronunciation_rules,
    build_xtts_profile_patch,
    load_global_lexicon,
    scan_books_for_lexicon,
    validate_global_lexicon,
)
from .models import MetadataCandidate, MetadataExtractionResult
from .providers import search_online_book_metadata

__all__ = [
    "BookMetadataExtractor",
    "MetadataCandidate",
    "MetadataExtractionResult",
    "build_author_pronunciation_rules",
    "build_pronunciation_rules",
    "build_xtts_profile_patch",
    "extract_metadata_from_source",
    "guess_metadata_from_filename",
    "load_global_lexicon",
    "scan_books_for_lexicon",
    "search_online_book_metadata",
    "validate_global_lexicon",
]
