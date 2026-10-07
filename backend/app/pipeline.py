import json
import logging
import re

from pydantic import ValidationError

from .prompts import SYSTEM_PROMPT, build_fix_prompt, build_user_prompt
from .schema import Diagram, check_logic


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
    If trace is given, each raw model reply and its problems are appended to it."""
    user = build_user_prompt(text, [a.name for a in attachments])
    reply = await provider.complete(SYSTEM_PROMPT, user, attachments)
    for attempt in range(max_fixes + 1):
        diagram, errors = _problems(reply)
        if trace is not None:
            trace.append({"attempt": attempt + 1, "reply": reply, "problems": errors})
        if diagram is not None and not errors:
            log.info("diagram valid on attempt %d", attempt + 1)
            return diagram
        log.warning("attempt %d had problems: %s", attempt + 1, errors[:5])
        if attempt == max_fixes:
            raise PipelineError(
                f"The AI reply still had problems after {max_fixes + 1} tries: " + " ".join(errors[:3])
            )
        reply = await provider.complete(SYSTEM_PROMPT, build_fix_prompt(user, reply, errors), attachments)
    raise PipelineError("Unreachable")
