export type NodeInfo = { id: string; label: string; sourceRef?: string; confidence?: number };

const toText = (html: string) => {
  const d = document.createElement("div");
  d.innerHTML = html;
  return d.textContent ?? "";
};

/** Reads steps (and our custom fields) out of draw.io XML. Proves custom attributes survive editing. */
export function parseNodes(xml: string): NodeInfo[] {
  const doc = new DOMParser().parseFromString(xml, "text/xml");
  return Array.from(doc.querySelectorAll("object")).map((o) => ({
    id: o.getAttribute("id") ?? "",
    label: toText(o.getAttribute("label") ?? ""),
    sourceRef: o.getAttribute("source_ref") ?? undefined,
    confidence: o.hasAttribute("confidence") ? Number(o.getAttribute("confidence")) : undefined,
  }));
}
