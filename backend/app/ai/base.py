"""AI provider interface.

This is the seam that keeps the platform from being a Claude application. Every
consumer - job handlers, services, the API - depends only on :class:`AIProvider`
and the provider-neutral request/response models in ``app/domain/ai.py``.

To add a provider (GPT, Gemini, a local model), create a package under
``app/ai/providers/<name>/``, implement this interface, and register it in
``app/ai/registry.py``. Nothing in the core needs to change. The full recipe is
in docs/EXTENDING_THE_APPLICATION.md.

Contract notes for implementers:

* :meth:`check_availability` must never raise. A missing tool is a normal
  state that the UI displays, not an exception path.
* :meth:`generate` receives an ``on_output`` callback and should stream the
  underlying tool's output through it so the console component stays live.
* :meth:`generate` must honour ``cancel_token`` promptly.
* Provider-specific errors must be translated into
  :class:`~app.core.errors.AIError` subclasses so the API layer can present a
  Persian message instead of a stack trace.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from app.domain.ai import AIRequest, AIResponse, ProviderInfo
from app.domain.enums import AITaskType, ProviderCapability
from app.process import CancelToken

#: Called with each line of tool output. ``stream`` is "stdout" or "stderr".
OutputCallback = Callable[[str, str], None]


class AIProvider(ABC):
    """Base class for every AI text provider."""

    #: Stable identifier used in the database, the API and the settings file.
    id: str = ""
    #: Name shown in the provider selector.
    display_name: str = ""

    # -- identity ----------------------------------------------------------

    @property
    @abstractmethod
    def capabilities(self) -> list[ProviderCapability]:
        """Optional features this provider supports."""

    @property
    def supported_tasks(self) -> list[AITaskType]:
        """Tasks this provider can serve. Defaults to every text task."""
        return [task for task in AITaskType]

    # -- health ------------------------------------------------------------

    @abstractmethod
    def check_availability(self) -> ProviderInfo:
        """Report whether the provider can run right now.

        Must not raise. When the underlying tool is missing, return
        ``available=False`` with a Persian ``unavailable_reason``.
        """

    # -- execution ---------------------------------------------------------

    @abstractmethod
    def generate(
        self,
        request: AIRequest,
        *,
        on_output: OutputCallback | None = None,
        cancel_token: CancelToken | None = None,
    ) -> AIResponse:
        """Run one AI call and return the normalised result.

        Raises an :class:`~app.core.errors.AIError` subclass on failure and
        :class:`~app.core.errors.ProcessCancelledError` when cancelled.
        """

    # -- helpers available to subclasses -----------------------------------

    def supports(self, capability: ProviderCapability) -> bool:
        return capability in self.capabilities

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<{type(self).__name__} id={self.id!r}>"
