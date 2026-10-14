import json
import logging
import re

from pydantic import ValidationError

from .prompts import (AMEND_SYSTEM_PROMPT, SYSTEM_PROMPT, build_amend_prompt, build_fix_prompt, build_user_prompt,
                      response_schema)
from .schema import AI_NODE_TYPES, Diagram, check_logic


log = logging.getLogger("app.pipeline")


class PipelineError(Exception):
    pass


def parse_json(reply: str) -> dict:
    """Models sometimes wrap JSON in code fences or add a sentence. Pull out the object."""
    text = re.sub(r"^```(?:json)?|```$", "", reply.strip(), flags=re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise json.JSONDecodeError("no JSON object found", text, 0)
    return json.loads(text[start : end + 1])


def _problems(reply: str) -> tuple[Diagram | None, list[str]]:
    try:
        diagram = Diagram.model_validate(parse_json(reply))
    except json.JSONDecodeError as e:
        return None, [f"The reply was not valid JSON ({e.msg})."]
    except ValidationError as e:
        return None, [f"Field '{'.'.join(map(str, x['loc']))}': {x['msg']}" for x in e.errors()[:8]]
    return diagram, check_logic(diagram)


async def generate_diagram(text: str, provider, attachments=(), max_fixes: int = 2, trace: list | None = None) -> Diagram:
    """Ask the model, validate, and automatically ask again with the problems listed (up to max_fixes times).
    attachments are sent with every request, so fix rounds can still see the original files.
    If trace is given, each raw model reply, the model's reasoning summary (if any) and its problems are appended to it."""
    user = build_user_prompt(text, [a.name for a in attachments])
    return await _ask_until_valid(SYSTEM_PROMPT, user, provider, attachments, max_fixes, trace,
                                  response_schema(), _only_ai_types)


async def amend_diagram(diagram: Diagram, instruction: str, provider, max_fixes: int = 2,
                        trace: list | None = None) -> Diagram:
    """Apply a change described in plain words to an existing diagram, with the same validation as generate."""
    current = json.dumps(diagram.model_dump(by_alias=True), indent=1, ensure_ascii=False)
    user = build_amend_prompt(current, instruction)
    amended = await _ask_until_valid(AMEND_SYSTEM_PROMPT, user, provider, (), max_fixes, trace, response_schema(amend=True))
    return _keep_reviews(diagram, amended)


def _only_ai_types(d: Diagram) -> list[str]:
    """A new diagram may only use the short list of node types the prompt gives."""
    return [f"Step '{n.id}' uses type '{n.type}'. Use one of: {', '.join(AI_NODE_TYPES)}."
            for n in d.nodes if n.type not in AI_NODE_TYPES]


def _keep_reviews(before: Diagram, after: Diagram) -> Diagram:
    """Only a person marks items "reviewed". Items they reviewed stay reviewed if the amend left them unchanged;
    the AI cannot mark anything reviewed itself (it gets "stated", as the user asked for it)."""
    keys = {
        "lanes": lambda x: (x.id, x.name),
        "nodes": lambda x: (x.id, x.label, x.type, x.lane),
        "edges": lambda x: (x.source, x.target, x.label),
    }
    for group, key in keys.items():
        reviewed = {key(x) for x in getattr(before, group) if x.support == "reviewed"}
        for x in getattr(after, group):
            if key(x) in reviewed:
                x.support = "reviewed"
            elif x.support == "reviewed":
                x.support = "stated"
    return after


async def _ask_until_valid(system: str, user: str, provider, attachments, max_fixes: int, trace: list | None,
                           schema: dict | None = None, extra_checks=None) -> Diagram:
    # providers that support structured output (Gemini) get the JSON schema; others rely on the prompt
    kw = {"schema": schema} if schema and getattr(provider, "accepts_schema", False) else {}
    reply = await provider.complete(system, user, attachments, **kw)
    for attempt in range(max_fixes + 1):
        diagram, errors = _problems(reply)
        if diagram is not None and extra_checks:
            errors += extra_checks(diagram)
        if trace is not None:
            trace.append({"attempt": attempt + 1, "reply": reply, "problems": errors,
                          "thoughts": getattr(provider, "thoughts", None)})
        if diagram is not None and not errors:
            log.info("diagram valid on attempt %d", attempt + 1)
            return diagram
        log.warning("attempt %d had problems: %s", attempt + 1, errors[:5])
        if attempt == max_fixes:
            raise PipelineError(
                f"The AI reply still had problems after {max_fixes + 1} tries: " + " ".join(errors[:3])
            )
        reply = await provider.complete(system, build_fix_prompt(user, reply, errors), attachments, **kw)
    raise PipelineError("Unreachable")
