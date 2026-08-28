"""Text-to-speech layer.

* ``base.py``       provider interface (the extension seam)
* ``registry.py``   which providers exist and are usable
* ``assembler.py``  turns a script of text + pauses into one audio file
* ``providers/``    concrete backends (SAPI5 offline, Edge neural)
"""

from app.tts.base import TTSProvider, TTSProviderInfo
from app.tts.registry import TTSRegistry

__all__ = ["TTSProvider", "TTSProviderInfo", "TTSRegistry"]
