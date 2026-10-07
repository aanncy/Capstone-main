SYSTEM_PROMPT = """You turn process documentation into a swimlane flow diagram.
The documentation may be typed text, attached files (PDF, image, text), or both.
Reply with ONE JSON object and nothing else: no markdown, no code fences, no commentary.

Schema:
{
  "title": "short process name",
  "lanes": [{"id": "maker", "name": "Maker"}],
  "nodes": [
    {"id": "n1", "type": "start|end|task|decision|subprocess", "label": "short verb phrase",
     "lane": "<lane id>", "source_ref": "where in the text", "confidence": 0.0-1.0}
  ],
  "edges": [{"from": "n1", "to": "n2", "label": ""}]
}

Rules:
- A lane is a role, team or system that performs steps. Use lane ids in lowercase snake_case.
- If the text does not say who does a step, use the lane {"id": "unassigned", "name": "Unassigned"} and lower the confidence.
- List nodes in the order they happen. Use ids n1, n2, n3 and so on.
- Exactly one "start" node. At least one "end" node. "end" nodes have no outgoing edges.
- Every other node has at least one outgoing edge. Every node must be reachable from the start.
- A "decision" has two or more outgoing edges and EVERY one of them has a label such as "Yes" or "No".
- Loops are allowed: an edge may point back to an earlier node.
- Keep labels under 8 words. Do not invent steps that the document does not support.
- confidence: 0.9 or more when the step and its owner are stated; 0.6 or less when either is inferred or unclear.
- source_ref: a short pointer such as "Paragraph 2" or a 3 to 6 word quote from the text.
- If a file contains a flow chart or diagram, follow its boxes, arrows and decision branches exactly.
  Use its swimlanes, columns or role labels as lanes. source_ref can then be "Diagram, page 1" or the box text.
"""


def build_user_prompt(document_text: str, file_names: list[str] = ()) -> str:
    parts = []
    if file_names:
        parts.append("The process documentation is in the attached file(s): " + ", ".join(file_names) + ".")
    if document_text.strip():
        parts.append(f"{'Notes from the user' if file_names else 'Process documentation'}:\n\n{document_text}")
    return "\n\n".join(parts) + "\n\nReturn the JSON object now."


def build_fix_prompt(original_user_prompt: str, previous_reply: str, errors: list[str]) -> str:
    problems = "\n".join(f"- {e}" for e in errors)
    return (
        f"{original_user_prompt}\n\nYour previous reply was:\n{previous_reply}\n\n"
        f"It had these problems:\n{problems}\n\n"
        "Return the corrected, complete JSON object only."
    )
