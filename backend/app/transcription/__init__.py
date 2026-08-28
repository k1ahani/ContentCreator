"""Speech-to-text layer.

Separate from ``app/ai/`` because turning audio into *timed* text is a
different capability from text generation - see ``base.py`` for the reasoning.
"""

from app.transcription.base import (
    EngineModel,
    TranscriptionProvider,
    TranscriptionProviderInfo,
)
from app.transcription.registry import TranscriptionRegistry

__all__ = [
    "EngineModel",
    "TranscriptionProvider",
    "TranscriptionProviderInfo",
    "TranscriptionRegistry",
]
