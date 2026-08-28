"""Job handlers, one module per job type.

To add a job type: add a member to :class:`~app.domain.enums.JobType`, create a
module here decorated with ``@register_handler(JobType.X)``, and import it in
``app/jobs/registry.py:load_handlers``. Startup verification then enforces that
the mapping is complete. See docs/JOB_SYSTEM.md.
"""
