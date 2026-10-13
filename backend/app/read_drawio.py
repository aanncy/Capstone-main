"""draw.io XML -> Diagram JSON, so a diagram the user has edited in draw.io can go back to the AI for amending.
Reads what to_drawio_xml writes (node_type, source_ref and confidence on every step), and also copes with
shapes and arrows drawn by hand in the editor: their type is guessed from the shape, their lane from the
swimlane they sit in."""
import base64
import html
import re
import zlib
import xml.etree.ElementTree as ET
from typing import get_args
from urllib.parse import unquote

from .schema import Diagram, NodeType


class DrawioError(Exception):
    """The XML is not a draw.io diagram we can read."""


NODE_TYPES = set(get_args(NodeType))
# For shapes drawn by hand: first match wins, so specific shapes come before general ones
TYPE_BY_STYLE = [
    ("rhombus", "decision"), ("flowchart.decision", "decision"),
    ("multi-document", "multiple_documents"), ("document", "document"),
    ("stored_data", "data_storage"), ("internalStorage", "internal_storage"),
    ("database", "database"), ("cylinder", "database"), ("manualInput", "manual_input"),
    ("trapezoid", "manual_operation"), ("parallelogram", "input_output"), ("flowchart.display", "display"),
    ("merge_or_storage", "merge"), ("shape=process", "subprocess"),
]
TERMINAL = ("arcSize=50", "terminator", "ellipse")  # rounded ends: a start or an end, depending on its arrows


def _text(s: str) -> str:
    """Cell labels may be HTML. Keep the words only."""
    s = re.sub(r"<br\s*/?>|</div>|</p>", " ", s or "", flags=re.I)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", s)).split())


def _model(xml: str) -> ET.Element:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as e:
        raise DrawioError(f"The diagram XML could not be read ({e}).") from e
    if root.tag == "mxGraphModel":
        return root
    page = root.find("diagram")
    if page is None:
        raise DrawioError("The XML has no draw.io diagram in it.")
    model = page.find("mxGraphModel")
    if model is not None:
        return model
    try:  # draw.io can save a page compressed: base64, then raw deflate, then URL-encoding
        data = zlib.decompress(base64.b64decode((page.text or "").strip()), -15)
        return ET.fromstring(unquote(data.decode("utf-8")))
    except (ValueError, zlib.error, ET.ParseError) as e:
        raise DrawioError("The diagram page could not be decompressed.") from e


def from_drawio_xml(xml: str) -> Diagram:
    model = _model(xml)
    root = model.find("root")
    if root is None:
        raise DrawioError("The diagram is empty.")
    cells = {}  # id -> (attributes, mxCell); <object> wrappers carry the label and our custom fields
    for el in root:
        cell = el.find("mxCell") if el.tag in ("object", "UserObject") else el
        if cell is None or not el.get("id"):
            continue
        attrs = dict(cell.attrib) | dict(el.attrib)
        attrs.setdefault("label", attrs.get("value", ""))
        cells[el.get("id")] = (attrs, cell)

    def style(i):
        return cells[i][0].get("style", "")

    def is_lane(i):
        return cells[i][0].get("vertex") == "1" and "swimlane" in style(i)

    def geometry(i):
        g = cells[i][1].find("mxGeometry")
        if g is None or g.get("relative") == "1":
            return 0.0, 0.0, 0.0, 0.0
        return tuple(float(g.get(k, 0)) for k in ("x", "y", "width", "height"))

    def absolute(i):
        x, y, w, h = geometry(i)
        parent = cells[i][0].get("parent")
        if parent in cells and cells[parent][0].get("vertex") == "1":
            px, py, _, _ = absolute(parent)
            x, y = x + px, y + py
        return x, y, w, h

    lane_ids = [i for i in cells if is_lane(i)]
    lanes = {i: i.removeprefix("lane_") for i in lane_ids}
    edge_ids = [i for i, (a, _) in cells.items() if a.get("edge") == "1"]
    edge_labels = {}  # labels added in the editor sit in child cells of the arrow
    for i, (a, _) in cells.items():
        if a.get("vertex") == "1" and a.get("parent") in edge_ids:
            edge_labels.setdefault(a["parent"], []).append(_text(a["label"]))
    node_ids = [i for i, (a, _) in cells.items()
                if a.get("vertex") == "1" and not is_lane(i) and a.get("parent") not in edge_ids
                and not style(i).startswith("text;") and (_text(a["label"]) or style(i))]

    def lane_of(i):
        parent = cells[i][0].get("parent")
        while parent in cells:
            if parent in lanes:
                return lanes[parent]
            parent = cells[parent][0].get("parent")
        x, y, w, h = absolute(i)
        for lane in lane_ids:  # drawn outside any lane: use the lane it sits on top of
            lx, ly, lw, lh = absolute(lane)
            if lx <= x + w / 2 <= lx + lw and ly <= y + h / 2 <= ly + lh:
                return lanes[lane]
        return "unassigned"

    nodes = set(node_ids)
    edges = []
    for i in edge_ids:
        a = cells[i][0]
        if a.get("source") in nodes and a.get("target") in nodes:
            label = " ".join(filter(None, [_text(a["label"])] + edge_labels.get(i, [])))
            edges.append({"from": a["source"], "to": a["target"], "label": label})
    has_in = {e["to"] for e in edges}
    has_out = {e["from"] for e in edges}

    def node_type(i):
        given = cells[i][0].get("node_type")
        if given in NODE_TYPES:
            return given
        s = style(i)
        if "aspect=fixed" in s and "ellipse" in s:
            return "connector"
        for key, kind in TYPE_BY_STYLE:
            if key in s:
                return kind
        if any(key in s for key in TERMINAL):
            return "start" if i not in has_in else "end" if i not in has_out else "task"
        return "task"

    out_nodes = []
    for i in node_ids:
        a = cells[i][0]
        ours = "node_type" in a
        try:
            confidence = min(max(float(a.get("confidence", "")), 0.0), 1.0)
        except ValueError:
            confidence = 0.8 if ours else 1.0
        out_nodes.append({"id": i, "type": node_type(i), "label": _text(a["label"]), "lane": lane_of(i),
                          "source_ref": a.get("source_ref", "" if ours else "Added in the editor"),
                          "confidence": confidence})
    lane_list = [{"id": lanes[i], "name": _text(cells[i][0]["label"]) or lanes[i]} for i in lane_ids]
    if any(n["lane"] == "unassigned" for n in out_nodes) and "unassigned" not in lanes.values():
        lane_list.append({"id": "unassigned", "name": "Unassigned"})
    page = ET.fromstring(xml).find("diagram") if xml.lstrip().startswith("<mxfile") else None
    title = (page.get("name") if page is not None else None) or "Process"
    if not out_nodes:
        raise DrawioError("The diagram has no steps to amend.")
    return Diagram.model_validate({"title": title, "lanes": lane_list, "nodes": out_nodes, "edges": edges})
