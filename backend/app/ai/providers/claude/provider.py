"""Claude provider.

Implements :class:`~app.ai.base.AIProvider` on top of the local Claude CLI.

Attachments are **inlined into the prompt** rather than passed as file
arguments. The reason is reliability: in ``--print`` mode a tool call that
needs permission has nowhere to ask, so a run that depends on the Read tool can
stall or fail. Every attachment this platform sends is text (a transcript, a
draft, a subtitle body), so embedding it between explicit delimiters is both
deterministic and cheaper. Binary or oversized files are rejected with a clear
Persian message instead of being silently dropped.
"""

from __future__ import annotations

from pathlib import Path

from app.ai.base import AIProvider, OutputCallback
from app.ai.providers.claude.cli import ClaudeCLI
from app.ai.providers.claude.detect import CliDetection, detect_claude_cli
from app.core.errors import ClaudeCliNotFoundError, FileValidationError
from app.core.logging import get_logger
from app.domain.ai import AIRequest, AIResponse, ProviderInfo
from app.domain.enums import AITaskType, ProviderCapability
from app.process import CancelToken

logger = get_logger(__name__)

#: Largest attachment inlined into a prompt. Beyond this the caller should be
#: chunking the work instead.
MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024

_TEXT_SUFFIXES = frozenset(
    {".txt", ".md", ".srt", ".vtt", ".ass", ".json", ".csv", ".log", ""}
)


class ClaudeProvider(AIProvider):
    """The only provider implemented in version 1."""

    id = "claude"
    display_name = "Claude"

    def __init__(self, *, configured_path: str | None = None, timeout: int = 900) -> None:
        self._configured_path = configured_path
        self._timeout = timeout
        self._detection: CliDetection | None = None

    # -- identity ----------------------------------------------------------

    @property
    def capabilities(self) -> list[ProviderCapability]:
        return [
            ProviderCapability.SYSTEM_PROMPT,
            ProviderCapability.MODEL_SELECTION,
            ProviderCapability.FILE_INPUT,
        ]

    @property
    def supported_tasks(self) -> list[AITaskType]:
        return list(AITaskType)

    # -- health ------------------------------------------------------------

    def detect(self, *, refresh: bool = False) -> CliDetection:
        """Locate the CLI, caching the result for the process lifetime."""
        if self._detection is None or refresh:
            self._detection = detect_claude_cli(self._configured_path)
        return self._detection

    def check_availability(self) -> ProviderInfo:
        from app.ai.models import ModelRegistry

        detection = self.detect(refresh=True)
        registry = ModelRegistry.load()
        return ProviderInfo(
            id=self.id,
            display_name=self.display_name,
            available=detection.found,
            unavailable_reason=None if detection.found else detection.error,
            version=detection.version,
            executable_path=str(detection.path) if detection.path else None,
            capabilities=self.capabilities,
            supported_tasks=self.supported_tasks,
            models=registry.list(provider=self.id),
        )

    def _cli(self) -> ClaudeCLI:
        detection = self.detect()
        if not detection.found or detection.path is None:
            raise ClaudeCliNotFoundError(detection.error or "claude CLI not found")
        return ClaudeCLI(detection.path, default_timeout=self._timeout)

    # -- execution ---------------------------------------------------------

    def generate(
        self,
        request: AIRequest,
        *,
        on_output: OutputCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> AIResponse:
        cli = self._cli()
        prompt = self._compose_prompt(request)

        result = cli.run(
            prompt,
            model=request.model,
            system_prompt=request.system_prompt,
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
            metadata={
                "usage": result.usage,
                "session_id": result.session_id,
                "cost_usd": result.cost_usd,
                "requested_model": request.model,
            },
        )

    # -- prompt assembly ---------------------------------------------------

    def _compose_prompt(self, request: AIRequest) -> str:
        """Inline attachments beneath the instruction text."""
        if not request.attachments:
            return request.prompt

        blocks = [request.prompt.strip()]
        for path in request.attachments:
            blocks.append(self._render_attachment(Path(path)))
        return "\n\n".join(blocks)

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
        # Fenced with the filename so the model can refer to it unambiguously.
        return f"--- FILE: {path.name} ---\n{content}\n--- END FILE: {path.name} ---"
