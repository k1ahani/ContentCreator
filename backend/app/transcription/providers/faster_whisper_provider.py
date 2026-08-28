"""Local Whisper transcription via faster-whisper (CTranslate2).

Runs entirely on the CPU, offline, and produces word-level timestamps - which
is exactly what the subtitle timeline needs.

Two implementation notes that matter:

**The import is lazy.** ``faster_whisper`` pulls in ctranslate2, onnxruntime and
numpy, which is a slow import and an optional dependency. Importing it at module
scope would make the whole backend fail to start when the ASR extra is not
installed. Instead the import happens inside the call, and a missing package
becomes a clean Persian "engine not installed" state.

**Models are cached in the project, not in the user profile.** Hugging Face
would otherwise scatter multi-hundred-megabyte weights under
``~/.cache/huggingface``. Pointing ``download_root`` at ``storage/models`` keeps
everything the platform downloads inside the project directory, where the user
can see and delete it.

Model sizes are a real trade-off for Persian, which is less represented in
Whisper's training data than English. ``small`` is the default because ``base``
degrades noticeably on Persian while ``medium`` is roughly three times slower on
CPU for a modest gain.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from app.core.errors import (
    ProcessCancelledError,
    TranscriptionEngineNotAvailableError,
)
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.domain.enums import LANGUAGE_METADATA, Language
from app.domain.transcription import (
    TranscriptionOptions,
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
)
from app.process import CancelToken
from app.transcription.base import (
    EngineModel,
    LogCallback,
    ProgressCallback,
    TranscriptionProvider,
    TranscriptionProviderInfo,
)

logger = get_logger(__name__)

#: Selectable Whisper sizes, smallest first.
ENGINE_MODELS: tuple[EngineModel, ...] = (
    EngineModel(
        id="tiny",
        label_fa="بسیار کوچک",
        size_mb=75,
        description_fa="سریع‌ترین گزینه؛ برای فارسی دقت پایینی دارد.",
    ),
    EngineModel(
        id="base",
        label_fa="کوچک",
        size_mb=145,
        description_fa="سریع، اما برای فارسی هنوز خطای محسوسی دارد.",
    ),
    EngineModel(
        id="small",
        label_fa="متوسط (پیشنهادی)",
        size_mb=470,
        description_fa="تعادل مناسب میان دقت و سرعت؛ برای فارسی و انگلیسی توصیه می‌شود.",
        recommended=True,
    ),
    EngineModel(
        id="medium",
        label_fa="بزرگ",
        size_mb=1500,
        description_fa="دقت بالاتر، اما روی پردازنده حدود سه برابر کندتر است.",
    ),
    EngineModel(
        id="large-v3",
        label_fa="بسیار بزرگ",
        size_mb=3100,
        description_fa="بیشترین دقت؛ روی پردازنده بسیار کند و نیازمند فضای زیاد است.",
    ),
)

DEFAULT_MODEL = "small"


class FasterWhisperProvider(TranscriptionProvider):
    """CPU Whisper inference through CTranslate2."""

    id = "faster_whisper"
    display_name = "Whisper محلی"

    def __init__(self, *, compute_type: str = "int8", cpu_threads: int = 0) -> None:
        # int8 quantisation is roughly 2x faster than float32 on CPU with no
        # meaningful accuracy loss for speech.
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self._model_cache: dict[str, Any] = {}

    # -- availability ------------------------------------------------------

    @staticmethod
    def _import_engine():
        """Import faster_whisper, translating absence into a domain error."""
        try:
            from faster_whisper import WhisperModel  # noqa: PLC0415
        except ImportError as exc:
            raise TranscriptionEngineNotAvailableError(
                f"faster-whisper is not installed: {exc}"
            ) from exc
        return WhisperModel

    def check_availability(self) -> TranscriptionProviderInfo:
        info = TranscriptionProviderInfo(
            id=self.id,
            display_name=self.display_name,
            offline=True,
            supported_languages=list(Language),
            provides_word_timings=True,
            models=[self._model_status(model) for model in ENGINE_MODELS],
        )

        try:
            import faster_whisper  # noqa: PLC0415
        except ImportError as exc:
            info.available = False
            info.unavailable_reason = "موتور تبدیل گفتار به متن نصب نشده است."
            info.hint = "اسکریپت scripts/install_asr.ps1 را اجرا کنید."
            logger.info("faster-whisper unavailable: %s", exc)
            return info

        info.available = True
        info.version = getattr(faster_whisper, "__version__", None)
        return info

    def _model_status(self, model: EngineModel) -> EngineModel:
        """Copy the descriptor with ``downloaded`` filled in from the cache."""
        cache_dir = PATHS.models_cache
        # huggingface_hub lays weights out as models--<org>--<repo>.
        marker = f"models--Systran--faster-whisper-{model.id}"
        downloaded = (cache_dir / marker).is_dir()
        return EngineModel(
            id=model.id,
            label_fa=model.label_fa,
            size_mb=model.size_mb,
            description_fa=model.description_fa,
            downloaded=downloaded,
            recommended=model.recommended,
        )

    # -- model loading -----------------------------------------------------

    def _load_model(self, model_size: str, on_log: LogCallback | None):
        """Load (and cache) a Whisper model, downloading weights on first use."""
        if model_size in self._model_cache:
            return self._model_cache[model_size]

        WhisperModel = self._import_engine()
        PATHS.models_cache.mkdir(parents=True, exist_ok=True)

        if on_log:
            on_log("system", f"loading whisper model '{model_size}' (first run may download weights)")
        logger.info("loading faster-whisper model %r", model_size)

        started = time.monotonic()
        try:
            model = WhisperModel(
                model_size,
                device="cpu",
                compute_type=self.compute_type,
                cpu_threads=self.cpu_threads,
                download_root=str(PATHS.models_cache),
            )
        except Exception as exc:
            raise TranscriptionEngineNotAvailableError(
                f"could not load whisper model {model_size!r}: {exc}",
                user_message="بارگذاری مدل تبدیل گفتار به متن ممکن نشد.",
                hint="اتصال اینترنت را برای دانلود اولیه مدل بررسی کنید یا مدل کوچک‌تری انتخاب کنید.",
            ) from exc

        logger.info("model %r ready in %.1fs", model_size, time.monotonic() - started)
        if on_log:
            on_log("system", f"model ready in {time.monotonic() - started:.1f}s")

        self._model_cache[model_size] = model
        return model

    # -- transcription -----------------------------------------------------

    def transcribe(
        self,
        audio_path: Path,
        options: TranscriptionOptions,
        *,
        on_progress: ProgressCallback | None = None,
        on_log: LogCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> TranscriptionResult:
        if not audio_path.is_file():
            raise TranscriptionEngineNotAvailableError(
                f"audio file not found: {audio_path}",
                user_message="فایل صوتی برای تبدیل به متن پیدا نشد.",
            )

        model_size = options.model_size or DEFAULT_MODEL
        model = self._load_model(model_size, on_log)
        started = time.monotonic()

        if on_progress:
            on_progress(None, "در حال آماده‌سازی صدا")

        language_code = (
            None
            if options.auto_detect_language
            else LANGUAGE_METADATA[options.language]["asr_code"]
        )

        if on_log:
            on_log(
                "system",
                f"transcribing {audio_path.name} lang={language_code or 'auto'} vad={options.vad_filter}",
            )

        try:
            segments_iter, info = model.transcribe(
                str(audio_path),
                language=language_code,
                task="transcribe",
                beam_size=5,
                vad_filter=options.vad_filter,
                # Trim long silences so cue boundaries land on real speech.
                vad_parameters={"min_silence_duration_ms": 500} if options.vad_filter else None,
                word_timestamps=True,
                initial_prompt=options.initial_prompt or None,
                condition_on_previous_text=True,
            )
        except Exception as exc:
            raise TranscriptionEngineNotAvailableError(
                f"whisper failed to start transcription: {exc}",
                user_message="اجرای موتور تبدیل گفتار به متن با خطا مواجه شد.",
            ) from exc

        total = float(getattr(info, "duration", 0.0) or 0.0)
        detected = getattr(info, "language", None)
        probability = getattr(info, "language_probability", None)

        if on_log:
            on_log("system", f"detected language={detected} p={probability:.2f}" if probability
                   else f"detected language={detected}")

        segments: list[TranscriptSegment] = []
        pieces: list[str] = []

        # faster-whisper yields lazily: work happens as we iterate, which is
        # what makes progress reporting and cancellation possible at all.
        for index, segment in enumerate(segments_iter):
            if cancel_token is not None and cancel_token.cancelled:
                raise ProcessCancelledError("transcription cancelled by user")

            text = (segment.text or "").strip()
            if not text:
                continue

            words = [
                TranscriptWord(
                    start=float(word.start),
                    end=float(word.end),
                    text=word.word,
                    probability=getattr(word, "probability", None),
                )
                for word in (getattr(segment, "words", None) or [])
                if word.start is not None and word.end is not None
            ]

            segments.append(
                TranscriptSegment(
                    index=index,
                    start=float(segment.start),
                    end=float(segment.end),
                    text=text,
                    words=words,
                    confidence=getattr(segment, "avg_logprob", None),
                )
            )
            pieces.append(text)

            if on_progress and total > 0:
                on_progress(
                    min(float(segment.end) / total, 0.99),
                    f"در حال تبدیل گفتار به متن ({len(segments)} قطعه)",
                )
            if on_log:
                on_log("stdout", f"[{segment.start:7.2f} -> {segment.end:7.2f}] {text}")

        if on_progress:
            on_progress(1.0, "تبدیل گفتار به متن کامل شد")

        elapsed = time.monotonic() - started
        logger.info(
            "transcribed %s: %d segments, %.1fs audio in %.1fs",
            audio_path.name,
            len(segments),
            total,
            elapsed,
        )

        return TranscriptionResult(
            text=" ".join(pieces).strip(),
            language=options.language,
            detected_language=detected,
            language_probability=probability,
            duration_seconds=total,
            segments=segments,
            engine=self.id,
            model=model_size,
            processing_seconds=elapsed,
        )
