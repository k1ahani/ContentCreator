"""Settings service tests: default overlay, validation, typed accessors."""

from __future__ import annotations

import pytest

from app.core.errors import ValidationError
from app.db.connection import Database
from app.db.migrations.runner import migrate
from app.db.repositories.settings import SettingsRepository
from app.domain.enums import Language
from app.services.settings import DEFAULTS, SettingsService


@pytest.fixture
def service(tmp_path) -> SettingsService:
    db = Database(tmp_path / "settings.db")
    migrate(db)
    return SettingsService(SettingsRepository(db))


class TestDefaults:
    def test_get_returns_builtin_default_when_unset(self, service: SettingsService):
        assert service.get("media.audio_preset") == DEFAULTS["media.audio_preset"]

    def test_all_includes_every_default_key(self, service: SettingsService):
        values = service.all()
        assert set(DEFAULTS).issubset(values)

    def test_unknown_key_raises(self, service: SettingsService):
        with pytest.raises(ValidationError):
            service.set("nonexistent.key", "value")


class TestPersistence:
    def test_set_then_get_returns_stored_value(self, service: SettingsService):
        service.set("media.audio_preset", "wav")
        assert service.get("media.audio_preset") == "wav"

    def test_reset_restores_default(self, service: SettingsService):
        service.set("media.audio_preset", "wav")
        service.reset("media.audio_preset")
        assert service.get("media.audio_preset") == DEFAULTS["media.audio_preset"]

    def test_reset_all_clears_every_override(self, service: SettingsService):
        service.update({"media.audio_preset": "wav", "voice.rate": 1.5})
        service.reset(None)
        assert service.get("media.audio_preset") == DEFAULTS["media.audio_preset"]
        assert service.get("voice.rate") == DEFAULTS["voice.rate"]

    def test_update_persists_multiple_keys_atomically(self, service: SettingsService):
        service.update({"voice.rate": 1.2, "voice.pitch": 2.0})
        assert service.get("voice.rate") == 1.2
        assert service.get("voice.pitch") == 2.0


class TestTypeValidation:
    def test_rejects_wrong_type_for_number(self, service: SettingsService):
        with pytest.raises(ValidationError):
            service.set("voice.rate", "fast")

    def test_rejects_wrong_type_for_bool(self, service: SettingsService):
        with pytest.raises(ValidationError):
            service.set("transcription.vad_filter", "yes")

    def test_accepts_int_for_float_default(self, service: SettingsService):
        service.set("voice.rate", 1)
        assert service.get("voice.rate") == 1

    def test_rejects_wrong_type_for_dict(self, service: SettingsService):
        with pytest.raises(ValidationError):
            service.set("ai.model_by_task", "not-a-dict")

    def test_rejects_wrong_type_for_list(self, service: SettingsService):
        with pytest.raises(ValidationError):
            service.set("general.allowed_import_roots", "not-a-list")


class TestSemanticValidation:
    def test_rejects_nonexistent_path(self, service: SettingsService):
        with pytest.raises(ValidationError):
            service.set("media.ffmpeg_path", "Z:/does/not/exist")

    def test_accepts_existing_path(self, service: SettingsService, tmp_path):
        service.set("media.ffmpeg_path", str(tmp_path))
        assert service.get("media.ffmpeg_path") == str(tmp_path)

    def test_rejects_unknown_ai_task_in_preferences(self, service: SettingsService):
        with pytest.raises(ValidationError):
            service.set("ai.model_by_task", {"not_a_real_task": "sonnet"})

    def test_accepts_valid_ai_task_preference(self, service: SettingsService):
        service.set("ai.model_by_task", {"translation": "opus"})
        assert service.model_preferences == {"translation": "opus"}

    def test_rejects_invalid_subtitle_colour(self, service: SettingsService):
        style = dict(DEFAULTS["subtitle.style"])
        style["text_color"] = "not-a-colour"
        with pytest.raises(ValidationError):
            service.set("subtitle.style", style)

    def test_accepts_valid_subtitle_style(self, service: SettingsService):
        style = dict(DEFAULTS["subtitle.style"])
        style["font_size"] = 40
        service.set("subtitle.style", style)
        assert service.subtitle_style.font_size == 40

    def test_rejects_nonexistent_import_root(self, service: SettingsService):
        with pytest.raises(ValidationError):
            service.set("general.allowed_import_roots", ["Z:/nope"])


class TestTypedAccessors:
    def test_claude_cli_path_none_when_blank(self, service: SettingsService):
        assert service.claude_cli_path is None

    def test_ffmpeg_path_none_when_blank(self, service: SettingsService):
        assert service.ffmpeg_path is None

    def test_max_import_bytes_is_megabytes_converted(self, service: SettingsService):
        service.set("general.max_import_size_mb", 100)
        assert service.max_import_bytes == 100 * 1024 * 1024

    def test_subtitle_style_returns_model(self, service: SettingsService):
        style = service.subtitle_style
        assert style.font_family

    def test_grouped_organises_by_section(self, service: SettingsService):
        grouped = service.grouped()
        assert "voice" in grouped
        assert "rate" in grouped["voice"]
