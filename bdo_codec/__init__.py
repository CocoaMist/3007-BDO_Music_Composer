"""Public API for the independent Black Desert music score v9 codec."""

from .codec import (
    build_plaintext, compare_score_documents, decode_score, document_from_dict,
    document_to_dict, encode_score, read_score, validate_score, write_score,
)
from .model import *  # noqa: F401,F403
from .model import __all__ as _model_exports
from .adapter import document_matches_logical_tracks, score_summary

__all__ = [
    *_model_exports,
    "build_plaintext", "compare_score_documents", "decode_score", "document_from_dict",
    "document_to_dict", "encode_score", "read_score", "validate_score", "write_score",
    "document_matches_logical_tracks", "score_summary",
]
