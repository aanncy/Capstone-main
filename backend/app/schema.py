"""The JSON contract between the AI, the validator, the layout and the converter."""
from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

NodeType = Literal[
    "start", "end", "task", "decision", "parallel", "subprocess",
    "document", "multiple_documents", "data_storage", "internal_storage",
    "database", "manual_input", "manual_operation", "input_output", "display",
    "merge", "connector", "predefined_process",
]
# The types the AI may choose when it creates a diagram. A short list keeps it from picking a special symbol for
# what is simply a task. The converter still draws every NodeType, so older diagrams and hand-picked shapes work.
AI_NODE_TYPES = ["start", "end", "task", "decision", "parallel", "subprocess", "document", "database"]

# How directly the sources support an item. The AI picks one of the first four; only a person sets "reviewed".
Support = Literal["stated", "derived", "implied", "guess", "reviewed"]
AI_SUPPORT = ["stated", "derived", "implied", "guess"]
NEEDS_REVIEW = {"implied", "guess"}


class _Supported(BaseModel):
    """Lanes, nodes and edges carry a support category and the sources that back them."""
    support: Support = "derived"
    sources: list[str] = []

    @model_validator(mode="before")
    @classmethod
    def _from_confidence(cls, data):
        # diagrams saved before categories had a number from 0 to 1 instead (1 meant a person reviewed it)
        if isinstance(data, dict) and "support" not in data and "confidence" in data:
            c = float(data["confidence"])
            data = {**data, "support": "reviewed" if c >= 1 else "stated" if c >= 0.9 else "derived" if c >= 0.7
                    else "implied" if c >= 0.4 else "guess"}
        return data


class Lane(_Supported):
    id: str
    name: str


class Node(_Supported):
    id: str
    type: NodeType
    label: str
    lane: str                      # id of a lane
    source_ref: str = ""           # which source this step came from, and where in it


class Edge(_Supported):
    model_config = ConfigDict(populate_by_name=True)
    id: str = ""                   # e1, e2... (optional; the converter numbers edges without one)
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    label: str = ""


class Conflict(BaseModel):
    affects: list[str] = []        # ids of the lanes, nodes or edges involved
    description: str               # what each source says
    resolution: str = ""           # which version was drawn and why


class OpenQuestion(BaseModel):
    question: str
    affects: list[str] = []
    source_ref: str = ""


class SkippedSection(BaseModel):
    source: str = ""
    section: str
    reason: str = ""


class Diagram(BaseModel):
    title: str = "Process"
    lanes: list[Lane]
    nodes: list[Node]
    edges: list[Edge]
    conflicts: list[Conflict] = []
    open_questions: list[OpenQuestion] = []
    skipped_sections: list[SkippedSection] = []


def check_logic(d: Diagram) -> list[str]:
    """Checks a human would make. Returns plain-English problems (empty list = fine)."""
    errs: list[str] = []
    lane_ids = [l.id for l in d.lanes]
    node_ids = [n.id for n in d.nodes]
    for dup in sorted({i for i in lane_ids if lane_ids.count(i) > 1}):
        errs.append(f"Lane id '{dup}' is used more than once.")
    for dup in sorted({i for i in node_ids if node_ids.count(i) > 1}):
        errs.append(f"Step id '{dup}' is used more than once.")
    lanes, ids = set(lane_ids), set(node_ids)

    for n in d.nodes:
        if n.lane not in lanes:
            errs.append(f"Step '{n.id}' is in lane '{n.lane}', which is not in the lanes list.")
    good_edges = []
    for e in d.edges:
        if e.source not in ids or e.target not in ids:
            errs.append(f"Arrow {e.source} -> {e.target} points to a step id that does not exist.")
        else:
            good_edges.append(e)

    starts = [n for n in d.nodes if n.type == "start"]
    if len(starts) != 1:
        errs.append(f"There must be exactly one start step (found {len(starts)}).")
    if not any(n.type == "end" for n in d.nodes):
        errs.append("There must be at least one end step.")

    for n in d.nodes:
        outs = [e for e in good_edges if e.source == n.id]
        if n.type == "end" and outs:
            errs.append(f"End step '{n.id}' ('{n.label}') must not have outgoing arrows.")
        if n.type != "end" and not outs:
            errs.append(f"Step '{n.id}' ('{n.label}') has no outgoing arrow.")
        if n.type == "decision":
            if len(outs) < 2:
                errs.append(f"Decision '{n.id}' ('{n.label}') needs at least two exits.")
            elif any(not e.label.strip() for e in outs):
                errs.append(f"Every exit of decision '{n.id}' ('{n.label}') needs a label such as Yes or No.")
        if n.type == "parallel" and len(outs) < 2 and sum(e.target == n.id for e in good_edges) < 2:
            errs.append(f"Parallel step '{n.id}' must split the flow (2+ outgoing arrows) or join it (2+ incoming).")

    known = lanes | ids | {e.id for e in d.edges if e.id}
    for kind, items in (("Conflict", d.conflicts), ("Open question", d.open_questions)):
        for i, item in enumerate(items, start=1):
            missing = [x for x in item.affects if x not in known]
            if missing:
                errs.append(f"{kind} {i} refers to ids that do not exist: {', '.join(missing)}.")

    if len(starts) == 1 and not errs:
        seen, queue = {starts[0].id}, deque([starts[0].id])
        while queue:
            cur = queue.popleft()
            for e in good_edges:
                if e.source == cur and e.target not in seen:
                    seen.add(e.target)
                    queue.append(e.target)
        for n in d.nodes:
            if n.id not in seen:
                errs.append(f"Step '{n.id}' ('{n.label}') cannot be reached from the start step.")
    return errs
