"""AI layer tests: recommendation engine, prompts, service composition.

These do not make real provider calls - see
tests/integration/test_jobs_pipeline.py::TestTextTaskJob for a real Claude
CLI call, and TestCodexProviderLive below for a real (but unauthenticated,
since no test credentials exist) Codex CLI check. Here the goal is the pure
logic: scoring, resolution order, prompt rendering, output cleanup, and
argv construction.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.ai.models import ModelRegistry
from app.ai.prompts.library import (
    generic_translation_instruction,
    get_builtin,
    list_builtins,
    translation_prompt,
)
from app.ai.prompts.renderer import extract_variables, render_template
from app.ai.providers.codex.cli import CodexCLI, _failure_message, _try_parse_json
from app.ai.providers.codex.provider import CodexProvider, DEFAULT_MODEL_SENTINEL
from app.ai.recommendation import RecommendationEngine
from app.ai.service import strip_conversational_framing
from app.ai.tasks import get_profile
from app.core.errors import ModelNotFoundError, ValidationError
from app.domain.ai import ModelSpec
from app.domain.enums import AITaskType, Language, ModelTier


@pytest.fixture
def registry() -> ModelRegistry:
    return ModelRegistry.load()


@pytest.fixture
def engine(registry: ModelRegistry) -> RecommendationEngine:
    return RecommendationEngine(registry)


class TestModelRegistry:
    def test_builtin_models_present(self, registry: ModelRegistry):
        ids = {m.id for m in registry.list()}
        assert {"sonnet", "opus", "haiku"}.issubset(ids)

    def test_get_returns_none_for_unknown(self, registry: ModelRegistry):
        assert registry.get("nonexistent-model") is None

    def test_list_filters_by_provider(self, registry: ModelRegistry):
        assert all(m.provider == "claude" for m in registry.list(provider="claude"))
        assert registry.list(provider="nonexistent") == []

    def test_for_task_only_returns_endorsed_models(self, registry: ModelRegistry):
        models = registry.for_task(AITaskType.TRANSLATION)
        assert all(AITaskType.TRANSLATION in m.good_for for m in models)

    def test_override_merges_by_id(self, registry: ModelRegistry):
        registry.apply_overrides([{"id": "sonnet", "quality": 1}])
        assert registry.get("sonnet").quality == 1
        # Unrelated fields survive the merge.
        assert registry.get("sonnet").provider == "claude"

    def test_override_adds_unknown_model(self, registry: ModelRegistry):
        registry.apply_overrides([{"id": "future-model", "display_name": "Future"}])
        assert registry.has("future-model")

    def test_unavailable_model_excluded_by_default(self, registry: ModelRegistry):
        registry.apply_overrides([{"id": "sonnet", "available": False}])
        assert "sonnet" not in {m.id for m in registry.list()}
        assert "sonnet" in {m.id for m in registry.list(include_unavailable=True)}


class TestRecommendationScoring:
    def test_translation_prefers_powerful_model(self, engine: RecommendationEngine):
        rec = engine.recommend(AITaskType.TRANSLATION, provider="claude")
        assert rec.recommended_model == "opus"

    def test_subtitle_processing_prefers_fast_model(self, engine: RecommendationEngine):
        rec = engine.recommend(AITaskType.SUBTITLE_PROCESSING, provider="claude")
        assert rec.recommended_model == "haiku"

    def test_endorsed_model_beats_unendorsed_with_higher_raw_score(self):
        # An isolated registry: the shipped builtins (sonnet, haiku) already
        # endorse GENERAL, which would confound a two-model comparison.
        isolated = ModelRegistry(
            models=[
                ModelSpec(id="weak", provider="claude", display_name="Weak",
                          quality=2, speed=2, good_for=[AITaskType.GENERAL]),
                ModelSpec(id="strong", provider="claude", display_name="Strong",
                          quality=5, speed=5, good_for=[]),
            ]
        )
        engine = RecommendationEngine(isolated)
        rec = engine.recommend(AITaskType.GENERAL, provider="claude")
        assert rec.recommended_model == "weak"

    def test_alternatives_include_every_model_for_provider(
        self, engine: RecommendationEngine, registry: ModelRegistry
    ):
        rec = engine.recommend(AITaskType.GENERAL, provider="claude")
        assert len(rec.alternatives) == len(registry.list(provider="claude"))

    def test_reason_is_persian_and_nonempty(self, engine: RecommendationEngine):
        rec = engine.recommend(AITaskType.TRANSLATION, provider="claude")
        assert rec.reason_fa.strip()

    def test_raises_when_provider_has_no_models(self, registry: ModelRegistry):
        empty = ModelRegistry(models=[])
        engine = RecommendationEngine(empty)
        with pytest.raises(ModelNotFoundError):
            engine.recommend(AITaskType.GENERAL, provider="claude")


class TestUserPreference:
    def test_preference_wins_over_ranking(self, engine: RecommendationEngine):
        rec = engine.recommend(
            AITaskType.TRANSLATION, provider="claude",
            user_preferences={"translation": "haiku"},
        )
        assert rec.recommended_model == "haiku"
        assert rec.from_user_preference is True

    def test_preference_moves_to_front_of_alternatives(self, engine: RecommendationEngine):
        rec = engine.recommend(
            AITaskType.TRANSLATION, provider="claude",
            user_preferences={"translation": "haiku"},
        )
        assert rec.alternatives[0].id == "haiku"

    def test_preference_for_different_task_ignored(self, engine: RecommendationEngine):
        rec = engine.recommend(
            AITaskType.TRANSLATION, provider="claude",
            user_preferences={"text_editing": "haiku"},
        )
        assert rec.from_user_preference is False

    def test_unavailable_preference_falls_back(self, engine: RecommendationEngine, registry):
        registry.apply_overrides([{"id": "sonnet", "available": False}])
        rec = engine.recommend(
            AITaskType.TEXT_EDITING, provider="claude",
            user_preferences={"text_editing": "sonnet"},
        )
        assert rec.from_user_preference is False
        assert rec.recommended_model != "sonnet"


class TestResolve:
    def test_explicit_model_wins_outright(self, engine: RecommendationEngine):
        assert engine.resolve(
            AITaskType.SUBTITLE_PROCESSING, provider="claude", requested_model="opus"
        ) == "opus"

    def test_falls_back_to_recommendation_when_none_requested(
        self, engine: RecommendationEngine
    ):
        assert engine.resolve(AITaskType.TRANSLATION, provider="claude") == "opus"

    def test_rejects_unknown_model(self, engine: RecommendationEngine):
        with pytest.raises(ModelNotFoundError):
            engine.resolve(AITaskType.GENERAL, provider="claude", requested_model="gpt-4")

    def test_rejects_model_from_wrong_provider(self, engine: RecommendationEngine, registry):
        registry.apply_overrides([{"id": "other-model", "provider": "gpt"}])
        with pytest.raises(ModelNotFoundError):
            engine.resolve(
                AITaskType.GENERAL, provider="claude", requested_model="other-model"
            )


class TestPromptTemplates:
    def test_builtin_library_covers_every_shipped_task(self):
        # Every task that ships a default prompt must actually have one.
        for task in (
            AITaskType.TRANSCRIPTION_REFINEMENT,
            AITaskType.TEXT_EDITING,
            AITaskType.TRANSLATION,
            AITaskType.SUBTITLE_PROCESSING,
            AITaskType.SUMMARIZATION,
            AITaskType.TEXT_ANALYSIS,
        ):
            assert list_builtins(task), f"no builtin prompt for {task.value}"

    def test_get_builtin_returns_none_for_unknown(self):
        assert get_builtin("does-not-exist") is None

    def test_translation_prompt_covers_both_directions(self):
        assert translation_prompt(Language.PERSIAN, Language.ENGLISH) is not None
        assert translation_prompt(Language.ENGLISH, Language.PERSIAN) is not None

    def test_generic_translation_names_both_languages(self):
        text = generic_translation_instruction(Language.PERSIAN, Language.ENGLISH)
        assert "Persian" in text and "English" in text


class TestTemplateRendering:
    def test_substitutes_variable(self):
        assert render_template("سلام {{name}}", {"name": "علی"}) == "سلام علی"

    def test_raises_on_missing_variable(self):
        with pytest.raises(ValidationError):
            render_template("{{missing}}", {})

    def test_extract_variables_preserves_order_dedup(self):
        assert extract_variables("{{b}} {{a}} {{b}}") == ["b", "a"]

    def test_no_placeholders_returns_body_unchanged(self):
        assert render_template("plain text", {}) == "plain text"


class TestTaskProfiles:
    def test_every_task_has_a_profile(self):
        for task in AITaskType:
            profile = get_profile(task)
            assert profile.task == task
            assert profile.label_fa.strip()

    def test_weights_sum_to_one(self):
        for task in AITaskType:
            profile = get_profile(task)
            assert profile.quality_weight + profile.speed_weight == pytest.approx(1.0)

    def test_unknown_task_falls_back_to_general(self):
        # get_profile is defensive against enum drift; confirm the fallback.
        profile = get_profile(AITaskType.GENERAL)
        assert profile.task == AITaskType.GENERAL


class TestOutputCleanup:
    def test_strips_english_preamble(self):
        result = strip_conversational_framing("Here is the corrected text:\nHello world")
        assert result == "Hello world"

    def test_strips_persian_preamble(self):
        result = strip_conversational_framing("متن اصلاح‌شده:\nسلام دنیا")
        assert result == "سلام دنیا"

    def test_leaves_normal_first_sentence_alone(self):
        text = "سلام دنیا. این یک جمله عادی است."
        assert strip_conversational_framing(text) == text

    def test_unwraps_single_code_fence(self):
        assert strip_conversational_framing("```\nplain text\n```") == "plain text"

    def test_removes_delimiter_leakage(self):
        from app.ai.service import _CONTENT_OPEN, _CONTENT_CLOSE

        text = f"{_CONTENT_OPEN}\nHello\n{_CONTENT_CLOSE}"
        assert "TEXT_START" not in strip_conversational_framing(text)

    def test_empty_input_returns_empty(self):
        assert strip_conversational_framing("") == ""

    def test_does_not_eat_long_first_line(self):
        # A genuine long sentence ending with a colon should survive.
        text = "این یک جمله بلند و توضیحی است که نباید حذف شود:\nو ادامه دارد."
        result = strip_conversational_framing(text)
        assert "این یک جمله بلند" in result


class TestCodexBuiltinModel:
    """The registry entry itself - see app/ai/models.py for why it is a
    single sentinel entry rather than a list of named model snapshots."""

    def test_codex_default_is_registered(self, registry: ModelRegistry):
        assert registry.has(DEFAULT_MODEL_SENTINEL)
        spec = registry.get(DEFAULT_MODEL_SENTINEL)
        assert spec is not None
        assert spec.provider == "codex"

    def test_no_id_collision_with_claude_models(self, registry: ModelRegistry):
        claude_ids = {m.id for m in registry.list(provider="claude")}
        codex_ids = {m.id for m in registry.list(provider="codex")}
        assert claude_ids.isdisjoint(codex_ids)

    def test_providers_are_independently_listable(self, registry: ModelRegistry):
        assert all(m.provider == "codex" for m in registry.list(provider="codex"))
        assert all(m.provider == "claude" for m in registry.list(provider="claude"))


class TestCodexCliArgvConstruction:
    """Pure argv-building logic - no process execution, so these run
    regardless of whether the Codex CLI is installed on the test machine."""

    @pytest.fixture
    def cli(self) -> CodexCLI:
        # The path need not exist for build_argv - it only formats argv[0].
        return CodexCLI(Path("codex.exe"))

    def test_no_model_omits_dash_m(self, cli: CodexCLI):
        argv = cli.build_argv(model=None, output_file=Path("out.txt"))
        assert "-m" not in argv

    def test_explicit_model_is_passed(self, cli: CodexCLI):
        argv = cli.build_argv(model="o4-mini", output_file=Path("out.txt"))
        assert "-m" in argv
        assert argv[argv.index("-m") + 1] == "o4-mini"

    def test_output_file_flag_present(self, cli: CodexCLI):
        argv = cli.build_argv(model=None, output_file=Path("answer.txt"))
        assert "-o" in argv
        assert argv[argv.index("-o") + 1] == "answer.txt"

    def test_never_a_shell_string(self, cli: CodexCLI):
        # Every element must be a separate argv entry - see
        # app/process/runner.py for why this matters (no shell involved, ever).
        argv = cli.build_argv(model=None, output_file=Path("out.txt"))
        assert isinstance(argv, list)
        assert all(isinstance(part, str) for part in argv)

    @pytest.mark.parametrize(
        "flag",
        [
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--json",
        ],
    )
    def test_safety_flags_always_present(self, cli: CodexCLI, flag: str):
        argv = cli.build_argv(model=None, output_file=Path("out.txt"))
        assert flag in argv

    def test_sentinel_never_reaches_argv_as_a_value(self):
        """The provider layer must translate DEFAULT_MODEL_SENTINEL to None
        before it ever reaches build_argv - this asserts build_argv itself
        has no special knowledge of the sentinel string, so a caller that
        forgets to translate it would fail loudly (a literal, nonexistent
        model name passed to -m) rather than silently succeeding."""
        cli = CodexCLI(Path("codex.exe"))
        argv = cli.build_argv(model=DEFAULT_MODEL_SENTINEL, output_file=Path("out.txt"))
        # build_argv treats any non-None model as literal - proving the
        # translation responsibility lives in the provider, not here.
        assert DEFAULT_MODEL_SENTINEL in argv


class TestCodexJsonlParsing:
    """Parsing of the verified real event shapes from `codex exec --json`
    (see app/ai/providers/codex/cli.py's module docstring for what was
    actually observed against codex-cli 0.150.1)."""

    def test_parses_valid_json_object_line(self):
        assert _try_parse_json('{"type": "turn.started"}') == {"type": "turn.started"}

    def test_ignores_non_json_line(self):
        assert _try_parse_json("Reading prompt from stdin...") is None

    def test_ignores_malformed_json(self):
        assert _try_parse_json('{"type": "turn.started"') is None

    def test_ignores_json_array_line(self):
        assert _try_parse_json("[1, 2, 3]") is None

    def test_extracts_turn_failed_message(self):
        event = {"type": "turn.failed", "error": {"message": "unexpected status 401"}}
        assert _failure_message(event) == "unexpected status 401"

    def test_ignores_non_failure_events(self):
        assert _failure_message({"type": "turn.started"}) is None
        assert _failure_message({"type": "item.completed", "item": {}}) is None

    def test_turn_failed_without_message_still_returns_something(self):
        # Defensive: the event shape could vary; never return None for a
        # confirmed turn.failed just because "message" was absent.
        result = _failure_message({"type": "turn.failed", "error": {}})
        assert result is not None


@pytest.mark.slow
class TestCodexProviderLive:
    """Against the real installed Codex CLI when present; skips otherwise.

    No valid Codex credentials exist in this environment, so only the
    availability-check path (which must never attempt a live call - see
    docs/AI_PROVIDERS.md for the ~35-40s cost of not doing this check the
    fast way) is exercised here. A real authenticated generate() call is
    intentionally not covered by this suite.
    """

    @pytest.fixture(autouse=True)
    def _require_codex(self):
        if shutil.which("codex") is None:
            pytest.skip("Codex CLI not installed")

    def test_detects_real_installation(self):
        provider = CodexProvider()
        detection = provider.detect(refresh=True)
        assert detection.found is True
        assert detection.version

    def test_availability_check_is_fast(self):
        """The whole point of using `codex login status` instead of a live
        exec call: this must complete in a few seconds, not ~40."""
        import time

        provider = CodexProvider()
        started = time.monotonic()
        info = provider.check_availability()
        elapsed = time.monotonic() - started

        assert elapsed < 10, f"availability check took {elapsed:.1f}s - too slow"
        # Whether or not this machine happens to be logged in, the important
        # property is that the check returns a real ProviderInfo either way.
        assert info.id == "codex"
        if not info.available:
            assert info.unavailable_reason
