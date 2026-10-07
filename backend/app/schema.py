"""The JSON contract between the AI, the validator, the layout and the converter."""
from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NodeType = Literal["start", "end", "task", "decision", "subprocess"]


class Lane(BaseModel):
    id: str
    name: str


class Node(BaseModel):
    id: str
    type: NodeType
    label: str
    lane: str                      # id of a lane
    source_ref: str = ""           # where in the document this step came from
    confidence: float = Field(default=0.8, ge=0, le=1)


class Edge(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    source: str = Field(alias="from")
    target: str = Field(alias="to")
    label: str = ""


class Diagram(BaseModel):
    title: str = "Process"
    lanes: list[Lane]
    nodes: list[Node]
    edges: list[Edge]


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
