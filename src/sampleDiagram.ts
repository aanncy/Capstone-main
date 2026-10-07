// Hand-written swimlane diagram in draw.io XML. Used while the backend and converter do not exist yet.
// Pattern to keep: each lane is a "swimlane" container; each step is a child of its lane (parent=lane id);
// each step is wrapped in <object> so our own fields (source_ref, confidence) are stored as attributes.

export const SAMPLE_TEXT = `A customer submits a payment request. The maker prepares the supporting documents and sends them on. The approver reviews the request and checks whether the amount is within their limit. If details are missing, the request goes back to the maker. If it is within limit, compliance runs a sanctions check, and once it passes the payment is released.`;

const terminator = "rounded=1;arcSize=50;html=1;whiteSpace=wrap;fillColor=#e0f2fe;strokeColor=#0369a1;";
const task = "rounded=0;html=1;whiteSpace=wrap;fillColor=#ffffff;strokeColor=#334155;";
const decision = "rhombus;html=1;whiteSpace=wrap;fillColor=#fef9c3;strokeColor=#a16207;";
const lane = "swimlane;horizontal=0;startSize=32;html=1;whiteSpace=wrap;fillColor=#f8fafc;strokeColor=#94a3b8;fontStyle=1;";
const edge = "edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;strokeColor=#334155;";

const node = (id: string, label: string, style: string, parent: string, x: number, y: number, w: number, h: number, ref: string, conf: number) =>
  `<object label="${label}" id="${id}" source_ref="${ref}" confidence="${conf}"><mxCell style="${style}" vertex="1" parent="${parent}"><mxGeometry x="${x}" y="${y}" width="${w}" height="${h}" as="geometry"/></mxCell></object>`;

const link = (id: string, from: string, to: string, label = "") =>
  `<mxCell id="${id}" value="${label}" style="${edge}" edge="1" parent="1" source="${from}" target="${to}"><mxGeometry relative="1" as="geometry"/></mxCell>`;

const lanes = (id: string, name: string, y: number) =>
  `<mxCell id="${id}" value="${name}" style="${lane}" vertex="1" parent="1"><mxGeometry x="40" y="${y}" width="960" height="140" as="geometry"/></mxCell>`;

export const SAMPLE_XML = `<mxfile host="app"><diagram id="sample" name="Payment request"><mxGraphModel dx="1100" dy="700" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="0" pageScale="1" math="0" shadow="0"><root><mxCell id="0"/><mxCell id="1" parent="0"/>${lanes("lane_maker", "Maker", 40)}${lanes("lane_approver", "Approver", 180)}${lanes("lane_compliance", "Compliance", 320)}${node("n1", "Request received", terminator, "lane_maker", 64, 45, 120, 50, "Paragraph 1", 0.95)}${node("n2", "Prepare supporting documents", task, "lane_maker", 220, 40, 140, 60, "Paragraph 1", 0.85)}${node("n3", "Review request", task, "lane_approver", 400, 40, 130, 60, "Paragraph 1", 0.9)}${node("n4", "Amount within limit?", decision, "lane_approver", 580, 30, 140, 80, "Paragraph 1", 0.6)}${node("n5", "Run sanctions check", task, "lane_compliance", 585, 40, 130, 60, "Paragraph 1", 0.55)}${node("n6", "Payment released", terminator, "lane_compliance", 790, 45, 130, 50, "Paragraph 1", 0.9)}${link("e1", "n1", "n2")}${link("e2", "n2", "n3")}${link("e3", "n3", "n4")}${link("e4", "n4", "n5", "Yes")}${link("e5", "n5", "n6", "Passed")}${link("e6", "n4", "n2", "No, details missing")}</root></mxGraphModel></diagram></mxfile>`;
