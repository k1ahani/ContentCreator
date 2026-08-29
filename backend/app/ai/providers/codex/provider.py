"""OpenAI Codex provider.

Implements :class:`~app.ai.base.AIProvider` on top of the local Codex CLI
(``npm install -g @openai/codex``). This is the second concrete provider the
platform ships, alongside Claude - see ``docs/AI_PROVIDERS.md`` for the full
picture and what was verified empirically versus documented-but-unverified
(no valid Codex credentials were available while building this).

Attachments are inlined into the prompt for the same reason as the Claude
provider: a non-interactive run has nowhere to grant tool-use permission if
the model tries to read a file itself, so the text is embedded directly
instead of depending on that working.
"""

from __future__ import annotations

from pathlib import Path

from app.ai.base import AIProvider, OutputCallback
from app.ai.providers.codex.cli import CodexCLI
from app.ai.providers.codex.detect import (
    CliDetection,
    check_login_status,
    detect_codex_cli,
)
from app.core.errors import DependencyError, FileValidationError
from app.core.logging import get_logger
from app.domain.ai import AIRequest, AIResponse, ProviderInfo
from app.domain.enums import AITaskType, ProviderCapability
from app.process import CancelToken

logger = get_logger(__name__)

#: The registry's built-in Codex entry (see app/ai/models.py) - a sentinel
#: meaning "let the CLI pick its own current default", never a real `-m`
#: value. Passing it literally as `-m codex-default` would fail immediately
#: since no such model exists.
DEFAULT_MODEL_SENTINEL = "codex-default"

MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024
_TEXT_SUFFIXES = frozenset(
    {".txt", ".md", ".srt", ".vtt", ".ass", ".json", ".csv", ".log", ""}
)


class CodexNotFoundError(DependencyError):
    code = "codex_cli_not_found"
    default_user_message = "ابزار خط فرمان Codex پیدا نشد."

    def __init__(self, message: str = "codex executable not found", **kw) -> None:
        kw.setdefault(
            "hint",
            "دستور «npm install -g @openai/codex» را اجرا کنید یا مسیر آن را در تنظیمات وارد کنید.",
        )
        super().__init__(message, **kw)


class CodexProvider(AIProvider):
    """Second text-generation provider, on top of the OpenAI Codex CLI."""

    id = "codex"
    display_name = "OpenAI Codex"

    def __init__(self, *, configured_path: str | None = None, timeout: int = 900) -> None:
        self._configured_path = configured_path
        self._timeout = timeout
        self._detection: CliDetection | None = None

    @property
    def capabilities(self) -> list[ProviderCapability]:
        # SYSTEM_PROMPT: honoured by folding it into the prompt body (the
        # exec subcommand exposes no --system-prompt flag) - the interface
        # only promises the effect, not a particular mechanism.
        return [
            ProviderCapability.SYSTEM_PROMPT,
            ProviderCapability.MODEL_SELECTION,
            ProviderCapability.FILE_INPUT,
        ]

    @property
    def supported_tasks(self) -> list[AITaskType]:
        return list(AITaskType)

    def detect(self, *, refresh: bool = False) -> CliDetection:
        if self._detection is None or refresh:
            self._detection = detect_codex_cli(self._configured_path)
        return self._detection

    def check_availability(self) -> ProviderInfo:
        from app.ai.models import ModelRegistry

        detection = self.detect(refresh=True)
        registry = ModelRegistry.load()

        if not detection.found:
            return ProviderInfo(
                id=self.id,
                display_name=self.display_name,
                available=False,
                unavailable_reason=detection.error,
                capabilities=self.capabilities,
                supported_tasks=self.supported_tasks,
                models=registry.list(provider=self.id),
            )

        # The binary exists; a fast local check (never a live call - see
        # detect.py's module docstring for the measured cost of skipping this
        # and letting an unauthenticated exec call fail on its own).
        auth = check_login_status(detection.path)  # type: ignore[arg-type]
        if not auth.logged_in:
            return ProviderInfo(
                id=self.id,
                display_name=self.display_name,
                available=False,
                unavailable_reason="Codex CLI نصب است اما وارد حساب نشده است.",
                version=detection.version,
                executable_path=str(detection.path),
                capabilities=self.capabilities,
                supported_tasks=self.supported_tasks,
                models=registry.list(provider=self.id),
            )

        return ProviderInfo(
            id=self.id,
            display_name=self.display_name,
            available=True,
            version=detection.version,
            executable_path=str(detection.path),
            capabilities=self.capabilities,
            supported_tasks=self.supported_tasks,
            models=registry.list(provider=self.id),
        )

    def _cli(self) -> CodexCLI:
        detection = self.detect()
        if not detection.found or detection.path is None:
            raise CodexNotFoundError(detection.error or "codex CLI not found")
        return CodexCLI(detection.path, default_timeout=self._timeout)

    def generate(
        self,
        request: AIRequest,
        *,
        on_output: OutputCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> AIResponse:
        cli = self._cli()
        prompt = self._compose_prompt(request)

        # Translate the registry sentinel into "omit -m entirely" - see
        # DEFAULT_MODEL_SENTINEL above.
        model = request.model
        if model == DEFAULT_MODEL_SENTINEL:
            model = None

        result = cli.run(
            prompt,
            model=model,
            timeout_seconds=request.timeout_seconds,
            on_output=on_output,
            cancel_token=cancel_token,
        )

        return AIResponse(
            text=result.text,
            model=result.model,
            provider=self.id,
            duration_seconds=result.duration_seconds,
            exit_code=result.exit_code,
            stderr=result.stderr,
            metadata={"requested_model": request.model},
        )

    def _compose_prompt(self, request: AIRequest) -> str:
        """Fold the system prompt and any attachments into one prompt body.

        Codex's ``exec`` subcommand has no system-prompt flag (verified
        against its real ``--help`` output), so the instruction that would
        otherwise go there is prepended as a clearly delimited block instead.
        """
        blocks: list[str] = []
        if request.system_prompt:
            blocks.append(request.system_prompt.strip())
        blocks.append(request.prompt.strip())
        for path in request.attachments:
            blocks.append(self._render_attachment(Path(path)))
        return "\n\n".join(block for block in blocks if block)

    @staticmethod
    def _render_attachment(path: Path) -> str:
        if not path.is_file():
            raise FileValidationError(
                f"attachment does not exist: {path}",
                user_message="فایل پیوست پیدا نشد.",
            )
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            raise FileValidationError(
                f"attachment {path.suffix!r} is not a text format",
                user_message="فقط فایل‌های متنی را می‌توان به هوش مصنوعی پیوست کرد.",
            )
        size = path.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise FileValidationError(
                f"attachment is {size} bytes, limit is {MAX_ATTACHMENT_BYTES}",
                user_message="فایل پیوست بیش از حد بزرگ است.",
                details={"size": size, "limit": MAX_ATTACHMENT_BYTES},
            )
        content = path.read_text(encoding="utf-8", errors="replace")
        return f"--- FILE: {path.name} ---\n{content}\n--- END FILE: {path.name} ---"
