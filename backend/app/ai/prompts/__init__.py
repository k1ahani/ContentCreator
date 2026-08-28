"""Prompt system: reusable templates plus variable rendering."""

from app.ai.prompts.library import BUILTIN_PROMPTS, get_builtin, list_builtins
from app.ai.prompts.renderer import PromptTemplate, render_template

__all__ = [
    "BUILTIN_PROMPTS",
    "PromptTemplate",
    "get_builtin",
    "list_builtins",
    "render_template",
]
