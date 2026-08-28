"""AI layer.

Boundaries:

* ``base.py``            provider interface (the extension seam)
* ``registry.py``        which providers exist and are usable
* ``models.py``          model metadata, the only source of model identifiers
* ``recommendation.py``  which model to use for a task
* ``tasks.py``           task profiles
* ``prompts/``           prompt templates and rendering
* ``service.py``         the facade every caller should use
* ``providers/``         one package per provider implementation

Callers should depend on :class:`app.ai.service.AIService`, not on a concrete
provider. See docs/AI_SYSTEM.md.
"""
