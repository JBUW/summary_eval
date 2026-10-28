"""The real judge-call handler (ticket 06c).

Renders the judge's rubric with its placeholders and makes one completion
call per (item, judge) unit through the injected endpoint client (05a).
One call scores all three v1 qualities (never cross-averaged, no
composite): the result is one nullable value per quality, extracted by
the ticket-07 parse seam. Nothing extractable ⇒ None (the judges phase
warns, commits no row, and continues). Any EndpointError ⇒
RuntimeFailure carrying the transport detail only; the judges phase
wraps it with the item and the judge (fail-fast, exit 1).
"""
import re

from .endpoint_client import EndpointError
from .errors import RuntimeFailure
from .judge_parser import QUALITIES, parse_judge_response

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _render(text, transcript_text, generation_text, reference):
    def substitute(match):
        token = match.group(1)
        if token == "transcript":
            return transcript_text
        if token == "summary":
            return generation_text
        if token == "reference" and reference is not None:
            return reference
        return match.group(0)

    return _PLACEHOLDER.sub(substitute, text)


def render_judge_messages(judge_entry, transcript_text, generation_text, reference):
    """Render the judge's system/user messages for one unit.

    Single-pass substitution: ``{transcript}``, ``{summary}``, and
    ``{reference}`` (only when a reference is available) are replaced;
    every other token — including ``{reference}`` without a reference —
    passes through literal, and substituted values are never re-scanned.
    The system message is present only when ``system_content`` is
    non-empty (absent ≡ ``""``, the 06a template convention).
    """
    messages = []
    system_content = judge_entry.get("system_content") or ""
    if system_content:
        messages.append(
            {
                "role": "system",
                "content": _render(
                    system_content, transcript_text, generation_text, reference
                ),
            }
        )
    messages.append(
        {
            "role": "user",
            "content": _render(
                judge_entry["user_template"],
                transcript_text,
                generation_text,
                reference,
            ),
        }
    )
    return messages


def judge_call(
    client, judge_name, judge_entry, transcript_text, generation_text, reference
):
    """One judge completion for one (item, judge) unit (the 06b seam).

    Returns one nullable value per v1 quality (never cross-averaged, no
    composite) after the raw response passes through the ticket-07 parse
    seam; None when the parse seam rejects the response (the judges
    phase warns, commits no row, and continues). Any EndpointError
    (transport/HTTP failure, timeout, empty completion) becomes a
    RuntimeFailure carrying the transport detail only; the judges phase
    wraps it with the item and the judge.
    """
    messages = render_judge_messages(
        judge_entry, transcript_text, generation_text, reference
    )
    try:
        raw = client.complete(
            judge_entry["endpoint"],
            judge_entry["model_name"],
            messages,
            gen_params=judge_entry["gen_params"],
            api_key_env=judge_entry["api_key_env"],
        )
    except EndpointError as exc:
        raise RuntimeFailure(str(exc)) from exc
    parsed = parse_judge_response(raw)
    if parsed.rejected:
        return None
    return {quality: parsed.values.get(quality) for quality in QUALITIES}
