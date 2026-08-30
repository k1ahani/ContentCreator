"""User settings.

Defaults live **here, in code**, not in the database. A fresh install and an
upgraded one therefore behave identically, and adding a setting is a one-line
change with no migration: the database only ever stores values the user has
actually changed.

Keys are dotted and grouped by section (``ai.*``, ``media.*``, ``subtitle.*``,
``voice.*``, ``general.*``). The frontend settings page is generated from the
same grouping, so a new key appears in the right tab automatically.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.errors import ValidationError
from app.core.logging import get_logger
from app.core.paths import PATHS
from app.db.repositories.settings import SettingsRepository
from app.domain.enums import AITaskType, Language, SpeakingStyle
from app.domain.subtitle import SubtitleStyle

logger = get_logger(__name__)

# --------------------------------------------------------------------------
# Defaults
# --------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    # -- general ---------------------------------------------------------
    "general.workspace_dir": str(PATHS.projects),
    "general.default_output_dir": "",
    #: When non-empty, imports are restricted to these directory trees.
    #: Empty means "anywhere on a local drive", which is the sane default for a
    #: personal machine. See app/core/security.validate_import_path.
    "general.allowed_import_roots": [],
    "general.max_import_size_mb": 8192,
    "general.theme": "system",
    # -- ai --------------------------------------------------------------
    #: Which registered provider (see app/ai/registry.py) new AI calls use
    #: by default. Exposed directly in Settings -> AI as "ارائه‌دهنده هوش
    #: مصنوعی"; a per-call override always wins over this - see
    #: AIService.resolve_provider_id.
    "ai.provider": "claude",
    "ai.claude_cli_path": "",
    "ai.codex_cli_path": "",
    "ai.default_model": "sonnet",
    #: Per-task overrides, e.g. {"translation": "opus"}. Wins over the
    #: recommendation engine; see app/ai/recommendation.py.
    "ai.model_by_task": {},
    "ai.timeout_seconds": 900,
    "ai.default_language": Language.PERSIAN.value,
    #: The last custom instruction the user wrote in the text editor. Stored
    #: as a setting rather than a prompts-table row because it is a single
    #: "what I was last doing" value that follows the user across projects,
    #: not a named template they manage - see docs/TEXT_PROCESSING.md.
    "ai.custom_prompt": "",
    # -- transcription ---------------------------------------------------
    "transcription.engine": "faster_whisper",
    "transcription.model_size": "medium",
    "transcription.language": Language.PERSIAN.value,
    "transcription.vad_filter": True,
    #: Run the LLM refinement pass automatically after transcription.
    "transcription.auto_refine": True,
    # -- media -----------------------------------------------------------
    "media.ffmpeg_path": "",
    "media.audio_preset": "opus",
    "media.render_quality": "balanced",
    # -- subtitle --------------------------------------------------------
    "subtitle.style": SubtitleStyle().model_dump(mode="json"),
    "subtitle.max_chars": 84,
    "subtitle.target_chars": 42,
    "subtitle.min_duration": 1.0,
    "subtitle.max_duration": 7.0,
    "subtitle.export_format": "srt",
    # -- voice -----------------------------------------------------------
    "voice.provider": "edge",
    "voice.language": Language.PERSIAN.value,
    "voice.voice_id": "fa-IR-DilaraNeural",
    "voice.style": SpeakingStyle.NEUTRAL.value,
    "voice.rate": 1.0,
    "voice.pitch": 0.0,
    "voice.output_format": "mp3",
    #: Credentials for the API-backed speech providers. Empty means "not
    #: configured", which those providers report as a setup step rather than a
    #: failure - see app/tts/providers/elevenlabs.py. Changing any voice.*
    #: key rebuilds the TTS registry (ServiceContainer.invalidate), so a key
    #: pasted here works immediately without a restart.
    "voice.elevenlabs_api_key": "",
    "voice.elevenlabs_model": "eleven_multilingual_v2",
    "voice.openai_api_key": "",
    #: Point this at a local OpenAI-compatible speech server (for example
    #: http://localhost:8880/v1) to get free, fully offline synthesis through
    #: the same provider - see app/tts/providers/openai_compatible.py.
    "voice.openai_base_url": "https://api.openai.com/v1",
    "voice.openai_model": "gpt-4o-mini-tts",
    #: Sentence spoken by the voice-preview endpoint, per language. Kept as a
    #: setting rather than a constant so a user comparing voices for one
    #: specific project can audition them on that project's own wording.
    "voice.preview_text_fa": "سلام، این یک نمونه از صدای من است.",
    "voice.preview_text_en": "Hello, this is a sample of how I sound.",
}

#: Keys whose values are paths that must exist when non-empty.
_PATH_KEYS = frozenset(
    {
        "general.workspace_dir",
        "general.default_output_dir",
        "media.ffmpeg_path",
        "ai.claude_cli_path",
        "ai.codex_cli_path",
    }
)

#: Sections exposed to the settings page, in display order.
SECTIONS: tuple[str, ...] = (
    "general",
    "ai",
    "transcription",
    "media",
    "subtitle",
    "voice",
)


class SettingsService:
    """Reads and writes user settings, layering the database over defaults."""

    def __init__(self, repository: SettingsRepository) -> None:
        self.repo = repository

    # -- reading -----------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """One setting. Falls back to the built-in default, then ``default``."""
        fallback = DEFAULTS.get(key, default)
        return self.repo.get(key, fallback)

    def all(self) -> dict[str, Any]:
        """Every setting: defaults overlaid with stored values."""
        merged = dict(DEFAULTS)
        merged.update(self.repo.get_all())
        return merged

    def grouped(self) -> dict[str, dict[str, Any]]:
        """Settings arranged by section, for the settings page."""
        result: dict[str, dict[str, Any]] = {section: {} for section in SECTIONS}
        for key, value in self.all().items():
            section, _, name = key.partition(".")
            result.setdefault(section, {})[name] = value
        return result

    # -- writing -----------------------------------------------------------

    def set(self, key: str, value: Any) -> Any:
        """Validate and store one setting, returning the stored value."""
        validated = self._validate(key, value)
        self.repo.set(key, validated)
        logger.info("setting %s updated", key)
        return validated

    def update(self, values: dict[str, Any]) -> dict[str, Any]:
        """Validate and store several settings in one go."""
        validated = {key: self._validate(key, value) for key, value in values.items()}
        self.repo.set_many(validated)
        logger.info("updated %d setting(s): %s", len(validated), sorted(validated))
        return validated

    def reset(self, key: str | None = None) -> None:
        """Remove a stored override so the default applies again."""
        if key is None:
            self.repo.reset_all()
            logger.info("all settings reset to defaults")
        else:
            self.repo.delete(key)
            logger.info("setting %s reset to default", key)

    # -- validation --------------------------------------------------------

    def _validate(self, key: str, value: Any) -> Any:
        if key not in DEFAULTS:
            raise ValidationError(
                f"unknown setting key: {key!r}",
                user_message="این تنظیم شناخته شده نیست.",
                details={"key": key},
            )

        default = DEFAULTS[key]

        # Type must match the default's shape, with int accepted for float.
        if isinstance(default, bool):
            if not isinstance(value, bool):
                raise self._type_error(key, "boolean")
        elif isinstance(default, (int, float)) and not isinstance(default, bool):
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise self._type_error(key, "number")
        elif isinstance(default, str):
            if not isinstance(value, str):
                raise self._type_error(key, "text")
        elif isinstance(default, list):
            if not isinstance(value, list):
                raise self._type_error(key, "list")
        elif isinstance(default, dict):
            if not isinstance(value, dict):
                raise self._type_error(key, "object")

        if key in _PATH_KEYS and isinstance(value, str) and value.strip():
            path = Path(value).expanduser()
            if not path.exists():
                raise ValidationError(
                    f"path does not exist: {value}",
                    user_message="مسیر واردشده وجود ندارد.",
                    details={"key": key, "path": value},
                )

        if key == "ai.model_by_task":
            self._validate_model_by_task(value)

        if key == "subtitle.style":
            # Round-trip through the model so an invalid colour is rejected now
            # rather than at render time.
            try:
                return SubtitleStyle(**value).model_dump(mode="json")
            except Exception as exc:
                raise ValidationError(
                    f"invalid subtitle style: {exc}",
                    user_message="تنظیمات ظاهر زیرنویس معتبر نیست.",
                ) from exc

        if key == "general.allowed_import_roots":
            for entry in value:
                if not isinstance(entry, str) or not Path(entry).is_dir():
                    raise ValidationError(
                        f"import root is not a directory: {entry!r}",
                        user_message="یکی از پوشه‌های مجاز واردشده وجود ندارد.",
                    )

        return value

    @staticmethod
    def _validate_model_by_task(value: dict) -> None:
        valid_tasks = {task.value for task in AITaskType}
        for task_key in value:
            if task_key not in valid_tasks:
                raise ValidationError(
                    f"unknown AI task in model preferences: {task_key!r}",
                    user_message="یکی از انواع پردازش انتخاب‌شده معتبر نیست.",
                    details={"task": task_key},
                )

    @staticmethod
    def _type_error(key: str, expected: str) -> ValidationError:
        return ValidationError(
            f"setting {key!r} expects a {expected}",
            user_message="مقدار واردشده برای این تنظیم معتبر نیست.",
            details={"key": key, "expected": expected},
        )

    # -- typed accessors used across the app -------------------------------

    @property
    def subtitle_style(self) -> SubtitleStyle:
        return SubtitleStyle(**self.get("subtitle.style"))

    @property
    def model_preferences(self) -> dict[str, str]:
        value = self.get("ai.model_by_task") or {}
        return {str(k): str(v) for k, v in value.items()}

    @property
    def claude_cli_path(self) -> str | None:
        return (self.get("ai.claude_cli_path") or "").strip() or None

    @property
    def codex_cli_path(self) -> str | None:
        return (self.get("ai.codex_cli_path") or "").strip() or None

    @property
    def ffmpeg_path(self) -> str | None:
        return (self.get("media.ffmpeg_path") or "").strip() or None

    @property
    def max_import_bytes(self) -> int:
        return int(self.get("general.max_import_size_mb")) * 1024 * 1024

    @property
    def allowed_import_roots(self) -> list[Path]:
        return [Path(entry) for entry in self.get("general.allowed_import_roots") or []]
