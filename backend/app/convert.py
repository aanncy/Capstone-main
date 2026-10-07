"""Diagram JSON -> draw.io XML.
PLACEHOLDER LAYOUT: steps are placed left to right in list order, one lane per row.
Replace this with the ELK-based lane-aware layout (plan tasks 3.1 to 3.3)."""
import html

from .schema import Diagram

LANE_H, STEP, X0 = 140, 170, 60
SIZES = {"start": (120, 50), "end": (120, 50), "task": (130, 60), "subprocess": (130, 60), "decision": (140, 80)}
STYLES = {
    "start": "rounded=1;arcSize=50;html=1;whiteSpace=wrap;fillColor=#e0f2fe;strokeColor=#0369a1;",
    "end": "rounded=1;arcSize=50;html=1;whiteSpace=wrap;fillColor=#e0f2fe;strokeColor=#0369a1;",
    "task": "rounded=0;html=1;whiteSpace=wrap;fillColor=#ffffff;strokeColor=#334155;",
    "subprocess": "shape=process;html=1;whiteSpace=wrap;backgroundOutline=1;fillColor=#ffffff;strokeColor=#334155;",
    "decision": "rhombus;html=1;whiteSpace=wrap;fillColor=#fef9c3;strokeColor=#a16207;",
}
LANE = "swimlane;horizontal=0;startSize=32;html=1;whiteSpace=wrap;fillColor=#f8fafc;strokeColor=#94a3b8;fontStyle=1;"
EDGE = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;strokeColor=#334155;"


def _e(s: str) -> str:
    return html.escape(s, quote=True)


def to_drawio_xml(d: Diagram) -> str:
    width = max(960, X0 + len(d.nodes) * STEP + 40)
    lane_y = {l.id: 40 + i * LANE_H for i, l in enumerate(d.lanes)}
    out = ['<mxCell id="0"/>', '<mxCell id="1" parent="0"/>']
    for l in d.lanes:
        out.append(
            f'<mxCell id="lane_{_e(l.id)}" value="{_e(l.name)}" style="{LANE}" vertex="1" parent="1">'
            f'<mxGeometry x="40" y="{lane_y[l.id]}" width="{width}" height="{LANE_H}" as="geometry"/></mxCell>'
        )
    for i, n in enumerate(d.nodes):
        w, h = SIZES[n.type]
        out.append(
            f'<object label="{_e(n.label)}" id="{_e(n.id)}" source_ref="{_e(n.source_ref)}" confidence="{n.confidence}">'
            f'<mxCell style="{STYLES[n.type]}" vertex="1" parent="lane_{_e(n.lane)}">'
            f'<mxGeometry x="{X0 + i * STEP}" y="{(LANE_H - h) // 2}" width="{w}" height="{h}" as="geometry"/></mxCell></object>'
        )
    for i, e in enumerate(d.edges):
        out.append(
            f'<mxCell id="e{i + 1}" value="{_e(e.label)}" style="{EDGE}" edge="1" parent="1" source="{_e(e.source)}" target="{_e(e.target)}">'
            f'<mxGeometry relative="1" as="geometry"/></mxCell>'
        )
    return (
        f'<mxfile host="app"><diagram id="d1" name="{_e(d.title)}"><mxGraphModel dx="1100" dy="700" grid="1" gridSize="10" '
        f'guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" math="0" shadow="0"><root>'
        + "".join(out)
        + "</root></mxGraphModel></diagram></mxfile>"
    )
