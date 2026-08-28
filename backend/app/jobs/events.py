"""Job event bus.

Bridges the worker threads to the async world so the browser can watch a job
live over Server-Sent Events.

The threading problem this solves: job handlers run on worker **threads**, but
SSE responses are **async** generators on the event loop. ``asyncio.Queue`` is
not thread-safe, so a worker cannot simply put to it. Every publish is therefore
marshalled onto the loop with :meth:`asyncio.AbstractEventLoop.call_soon_threadsafe`.

SSE was chosen over WebSockets deliberately: job updates are strictly
server-to-client, SSE reconnects on its own, and it needs no extra protocol
handling on either side. There is nothing the client needs to send back over the
same channel - cancellation is an ordinary DELETE request.

Subscribers are bounded. A browser tab that stops reading must not let the
queue grow without limit, so an overfull subscriber loses its oldest events
rather than the server losing memory.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Final

from app.core.logging import get_logger
from app.domain.job import JobEvent

logger = get_logger(__name__)

#: Events buffered per subscriber before the oldest are dropped.
_QUEUE_MAXSIZE: Final = 500


class EventBus:
    """Fan-out of :class:`JobEvent` from worker threads to SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[JobEvent]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the loop that SSE responses run on. Called during startup."""
        self._loop = loop

    def close(self) -> None:
        with self._lock:
            self._subscribers.clear()
        self._loop = None

    # -- subscription ------------------------------------------------------

    def subscribe(self) -> asyncio.Queue[JobEvent]:
        """Register a subscriber. The caller must :meth:`unsubscribe`."""
        queue: asyncio.Queue[JobEvent] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        with self._lock:
            self._subscribers.add(queue)
        logger.debug("SSE subscriber added (%d total)", len(self._subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[JobEvent]) -> None:
        with self._lock:
            self._subscribers.discard(queue)
        logger.debug("SSE subscriber removed (%d left)", len(self._subscribers))

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    # -- publishing --------------------------------------------------------

    def publish(self, event: JobEvent) -> None:
        """Publish an event. Safe to call from any thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            # Before startup or after shutdown: nothing is listening.
            return

        with self._lock:
            targets = list(self._subscribers)
        if not targets:
            return

        for queue in targets:
            try:
                loop.call_soon_threadsafe(self._offer, queue, event)
            except RuntimeError:
                # Loop closed between the check and the call.
                return

    @staticmethod
    def _offer(queue: asyncio.Queue[JobEvent], event: JobEvent) -> None:
        """Enqueue, dropping the oldest event when a subscriber falls behind."""
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover
                pass
