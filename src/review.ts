/**
 * Low-confidence steps, lanes and connections for the user to review, read straight from the
 * draw.io XML (so it follows the user's own edits), and marking them reviewed (confidence 1).
 */

export type FlagLevel = "red" | "yellow";

export type Flag = {
  id: string;
  kind: "Step" | "Lane" | "Connection";
  label: string;
  confidence: number;
  level: FlagLevel;
};

export const REVIEW_BELOW = 0.7; // shown for review below this
export const RED_BELOW = 0.4; // red below this, yellow from here up to REVIEW_BELOW

const toText = (html: string) => {
  const d = document.createElement("div");
  d.innerHTML = html;
  return (d.textContent ?? "").replace(/\s+/g, " ").trim();
};

/** draw.io may save a page compressed: base64, then raw deflate, then URL-encoding. */
async function inflate(text: string): Promise<string> {
  const bytes = Uint8Array.from(atob(text.trim()), (c) => c.charCodeAt(0));
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return decodeURIComponent(await new Response(stream).text());
}

/** The XML as a document whose first page holds a plain mxGraphModel (decompressed if needed). */
async function readDoc(xml: string): Promise<Document | null> {
  const parser = new DOMParser();
  const doc = parser.parseFromString(xml, "text/xml");
  if (doc.querySelector("parsererror")) return null;
  const page = doc.querySelector("diagram");
  if (page && !page.querySelector("mxGraphModel") && page.textContent?.trim()) {
    try {
      const model = parser.parseFromString(await inflate(page.textContent), "text/xml");
      page.textContent = "";
      page.appendChild(doc.importNode(model.documentElement, true));
    } catch {
      return null;
    }
  }
  return doc;
}

/** Steps, lanes and connections with a stored confidence under REVIEW_BELOW, least sure first. */
export async function findFlags(xml: string): Promise<Flag[]> {
  const doc = await readDoc(xml);
  if (!doc) return [];
  const names = new Map<string, string>();
  doc.querySelectorAll("object, mxCell[id]").forEach((el) => {
    const label = el.getAttribute("label") ?? el.getAttribute("value");
    if (el.getAttribute("id") && label) names.set(el.getAttribute("id")!, toText(label));
  });
  const name = (id: string | null) => (id && names.get(id)) || "?";
  const flags: Flag[] = [];
  doc.querySelectorAll("object").forEach((o) => {
    const raw = o.getAttribute("confidence");
    const confidence = raw === null || raw === "" ? NaN : Number(raw);
    if (!(confidence < REVIEW_BELOW)) return;
    const cell = o.querySelector("mxCell");
    const label = toText(o.getAttribute("label") ?? "");
    let kind: Flag["kind"] = "Step";
    let text = label || "(no label)";
    if (cell?.getAttribute("edge") === "1") {
      kind = "Connection";
      text = `${name(cell.getAttribute("source"))} → ${name(cell.getAttribute("target"))}` + (label ? ` (${label})` : "");
    } else if ((cell?.getAttribute("style") ?? "").includes("swimlane")) {
      kind = "Lane";
    }
    flags.push({
      id: o.getAttribute("id") ?? "",
      kind,
      label: text,
      confidence,
      level: confidence < RED_BELOW ? "red" : "yellow",
    });
  });
  return flags.sort((a, b) => a.confidence - b.confidence);
}

/** The same diagram with these items set to confidence 1 (reviewed by a person). Reviewed arrows stop being dashed. */
export async function markReviewed(xml: string, ids: string[]): Promise<string> {
  const doc = await readDoc(xml);
  if (!doc) throw new Error("The diagram could not be read.");
  const wanted = new Set(ids);
  doc.querySelectorAll("object").forEach((o) => {
    if (!wanted.has(o.getAttribute("id") ?? "")) return;
    o.setAttribute("confidence", "1");
    const cell = o.querySelector("mxCell");
    const style = cell?.getAttribute("style");
    if (cell?.getAttribute("edge") === "1" && style) cell.setAttribute("style", style.replace(/(^|;)dashed=1;?/, "$1"));
  });
  return new XMLSerializer().serializeToString(doc);
}
