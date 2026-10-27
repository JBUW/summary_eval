"""Prompt template loading for score (docs/config.md prompt_templates)."""
import json
from dataclasses import dataclass

from .errors import RuntimeFailure


@dataclass(frozen=True)
class Template:
    system_content: str
    user_prefix: str


def load_template(name, path):
    """Load one configured prompt template (read/parse failure ⇒ exit 1)."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError:
        raise RuntimeFailure(f"template '{name}': file not found: {path}") from None
    except (OSError, UnicodeDecodeError) as exc:
        detail = getattr(exc, "strerror", None) or exc
        raise RuntimeFailure(f"template '{name}': cannot read {path}: {detail}") from None

    try:
        object_ = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeFailure(f"template '{name}': not valid JSON: {exc}") from exc

    if not isinstance(object_, dict):
        raise RuntimeFailure(
            f"template '{name}': must be a JSON object with string fields "
            "'system_content' and 'user_template'"
        )
    system_content = object_.get("system_content", "")
    user_template = object_.get("user_template", "")
    if not isinstance(system_content, str) or not isinstance(user_template, str):
        raise RuntimeFailure(
            f"template '{name}': 'system_content' and 'user_template' must be strings"
        )
    return Template(system_content=system_content, user_prefix=user_template)
