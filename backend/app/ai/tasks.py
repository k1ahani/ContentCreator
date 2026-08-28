"""Task profiles.

A *task profile* describes what a kind of AI work needs, independently of any
provider or model. The recommendation engine reads these weights to rank
models; the prompt library keys its built-in templates off the same task enum.

Adding a task means: add a member to :class:`~app.domain.enums.AITaskType`, add
a profile here, add a built-in prompt in ``app/ai/prompts/library.py``, and
list the task in the models that suit it in ``app/ai/models.py``. Nothing else
needs to change - see docs/EXTENDING_THE_APPLICATION.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from app.domain.enums import AITaskType, ModelTier


@dataclass(frozen=True, slots=True)
class TaskProfile:
    """Static metadata about one kind of AI work."""

    task: AITaskType
    #: Persian label shown in the UI.
    label_fa: str
    #: Persian one-line description.
    description_fa: str
    #: Tier the engine leans towards when no model explicitly declares the task.
    preferred_tier: ModelTier
    #: Ranking weights. They must sum to 1.0; quality-heavy tasks favour the
    #: stronger model, speed-heavy tasks favour the cheaper one.
    quality_weight: float
    speed_weight: float
    #: Whether the task output should be returned verbatim as content. When
    #: true the provider strips conversational framing aggressively, because
    #: the result goes straight into an editor rather than a chat transcript.
    expects_raw_text: bool = True
    #: Rough upper bound on useful input size, in characters. Longer inputs are
    #: chunked by the caller (see app/services/text_processing.py).
    max_input_chars: int = 60_000
    #: Extra Persian guidance appended to the system prompt for this task.
    system_notes_fa: tuple[str, ...] = field(default_factory=tuple)


_PROFILES: Final[dict[AITaskType, TaskProfile]] = {
    AITaskType.TRANSCRIPTION_REFINEMENT: TaskProfile(
        task=AITaskType.TRANSCRIPTION_REFINEMENT,
        label_fa="بازبینی رونوشت",
        description_fa=(
            "اصلاح علائم نگارشی، املا و یکدست‌سازی متنی که موتور گفتار به متن تولید کرده است."
        ),
        preferred_tier=ModelTier.BALANCED,
        quality_weight=0.6,
        speed_weight=0.4,
        max_input_chars=40_000,
        system_notes_fa=(
            "ترتیب و معنای جملات را تغییر نده؛ فقط خطاهای نگارشی و املایی را اصلاح کن.",
            "کلمات را حذف یا اضافه نکن مگر آنکه آشکارا اشتباه شنیداری باشند.",
        ),
    ),
    AITaskType.TEXT_EDITING: TaskProfile(
        task=AITaskType.TEXT_EDITING,
        label_fa="ویرایش متن",
        description_fa="اصلاح نگارشی، روان‌سازی و بهبود خوانایی متن بدون تغییر معنا.",
        preferred_tier=ModelTier.BALANCED,
        quality_weight=0.7,
        speed_weight=0.3,
    ),
    AITaskType.TRANSLATION: TaskProfile(
        task=AITaskType.TRANSLATION,
        label_fa="ترجمه",
        description_fa="ترجمه طبیعی و روان با حفظ لحن و معنای متن اصلی.",
        preferred_tier=ModelTier.POWERFUL,
        quality_weight=0.85,
        speed_weight=0.15,
        system_notes_fa=(
            "لحن، سطح رسمی‌بودن و منظور نویسنده را حفظ کن.",
            "اصطلاحات را تحت‌اللفظی ترجمه نکن؛ معادل طبیعی زبان مقصد را بیاور.",
        ),
    ),
    AITaskType.TEXT_ANALYSIS: TaskProfile(
        task=AITaskType.TEXT_ANALYSIS,
        label_fa="تحلیل متن",
        description_fa="بررسی ساختار، لحن، مخاطب و نکات قابل بهبود در متن.",
        preferred_tier=ModelTier.POWERFUL,
        quality_weight=0.8,
        speed_weight=0.2,
        expects_raw_text=False,
    ),
    AITaskType.SUBTITLE_PROCESSING: TaskProfile(
        task=AITaskType.SUBTITLE_PROCESSING,
        label_fa="پردازش زیرنویس",
        description_fa="تقسیم متن به قطعه‌های کوتاه و خوانا برای نمایش به‌عنوان زیرنویس.",
        preferred_tier=ModelTier.FAST,
        quality_weight=0.45,
        speed_weight=0.55,
        system_notes_fa=(
            "هر قطعه باید در یک نگاه خوانده شود و از دو خط بیشتر نشود.",
            "جمله را در جای طبیعی (بعد از نشانه نگارشی یا مرز عبارت) بشکن.",
        ),
    ),
    AITaskType.SUMMARIZATION: TaskProfile(
        task=AITaskType.SUMMARIZATION,
        label_fa="خلاصه‌سازی",
        description_fa="تولید خلاصه فشرده با حفظ نکات کلیدی متن.",
        preferred_tier=ModelTier.BALANCED,
        quality_weight=0.6,
        speed_weight=0.4,
        expects_raw_text=False,
    ),
    AITaskType.GENERAL: TaskProfile(
        task=AITaskType.GENERAL,
        label_fa="پردازش عمومی",
        description_fa="اجرای دستور دلخواه کاربر روی متن.",
        preferred_tier=ModelTier.BALANCED,
        quality_weight=0.5,
        speed_weight=0.5,
    ),
}


def get_profile(task: AITaskType) -> TaskProfile:
    """Return the profile for ``task``. Falls back to GENERAL for unknown values."""
    return _PROFILES.get(task, _PROFILES[AITaskType.GENERAL])


def all_profiles() -> list[TaskProfile]:
    return list(_PROFILES.values())
