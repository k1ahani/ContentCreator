"""Background job system.

* ``events.py``    thread-safe event bus feeding SSE
* ``context.py``   what a handler receives
* ``registry.py``  job type -> handler mapping
* ``queue.py``     worker pool and job lifecycle
* ``handlers/``    one module per job type
"""

from app.jobs.context import JobContext
from app.jobs.events import EventBus
from app.jobs.queue import JobQueue
from app.jobs.registry import get_handler, register_handler, registered_types

__all__ = [
    "EventBus",
    "JobContext",
    "JobQueue",
    "get_handler",
    "register_handler",
    "registered_types",
]
