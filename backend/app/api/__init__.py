"""HTTP API layer.

Routers are thin: they validate input, call a service or submit a job, and
serialise the result. Business logic lives in ``app/services``, ``app/jobs``
and the provider layers - never here. See docs/API.md.
"""
