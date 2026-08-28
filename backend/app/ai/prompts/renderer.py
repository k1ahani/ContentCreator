"""Prompt templates and variable substitution.

A template is text containing ``{{variable}}`` placeholders. Rendering is
deliberately *not* Python ``str.format`` or an f-string: prompt bodies contain
JSON examples full of braces, and a general-purpose formatter would choke on
them or, worse, interpret user text as a format spec.

The system is intentionally small in version 1 but shaped for what comes next -
saved prompts, categories and history all key off the same structure. See
docs/EXTENDING_THE_APPLICATION.md.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Mapping

from app.core.errors import ValidationError
from app.domain.enums import AITaskType

#: Matches ``{{ name }}`` with optional surrounding whitespace.
_PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


@dataclass(frozen=True, slots=True)
class PromptTemplate:
    """A reusable prompt body plus the metadata the UI needs."""

    id: str
    name_fa: str
    task: AITaskType
    body: str
    category: str = "general"
    description_fa: str = ""
    #: Variables the body expects. Derived from the body when not given.
    variables: tuple[str, ...] = field(default_factory=tuple)

    def declared_variables(self) -> tuple[str, ...]:
        return self.variables or tuple(sorted(set(_PLACEHOLDER.findall(self.body))))

    def render(self, values: Mapping[str, str] | None = None) -> str:
        return render_template(self.body, values)


def render_template(body: str, values: Mapping[str, str] | None = None) -> str:
    """Substitute ``{{variable}}`` placeholders.

    Raises :class:`ValidationError` when the body references a variable that was
    not supplied, so a half-rendered prompt never reaches a model.
    """
    supplied = dict(values or {})
    missing: list[str] = []

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in supplied:
            missing.append(name)
            return match.group(0)
        return str(supplied[name])

    rendered = _PLACEHOLDER.sub(replace, body)
    if missing:
        raise ValidationError(
            f"prompt template is missing variables: {sorted(set(missing))}",
            user_message="مقدار برخی متغیرهای این قالب مشخص نشده است.",
            details={"missing": sorted(set(missing))},
        )
    return rendered


def extract_variables(body: str) -> list[str]:
    """List the placeholders a body uses, in first-appearance order."""
    seen: list[str] = []
    for name in _PLACEHOLDER.findall(body):
        if name not in seen:
            seen.append(name)
    return seen
