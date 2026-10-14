/**
 * What the user should review, read straight from the draw.io XML (so it follows the user's own edits):
 * - steps, lanes and connections the AI classified as "implied" (yellow) or "guess" (red);
 * - conflicts between the sources (red) and open questions (yellow), kept on the diagram's root cell.
 * Marking an item reviewed sets its support to "reviewed", or removes the conflict / question.
 */

export type FlagLevel = "red" | "yellow";

export type Flag = {
  id: string; // a cell id, or "conflict:<n>" / "question:<n>"
  kind: "Step" | "Lane" | "Connection" | "Conflict" | "Open question";
  label: string;
  detail?: string;
  category: string; // what is shown after the kind: implied, guess, ...
  level: FlagLevel;
};

export type Skipped = { source: string; section: string; reason: string };

type Conflict = { affects?: string[]; description: string; resolution?: string };
type Question = { question: string; affects?: string[]; source_ref?: string };

const LEVEL: Record<string, FlagLevel> = { guess: "red", implied: "yellow" };
const ORDER: Record<FlagLevel, number> = { red: 0, yellow: 1 };

const toText = (html: string) => {
  const d = document.createElement("div");
  d.innerHTML = html;
  return (d.textContent ?? "").replace(/\s+/g, " ").trim();
};

/** Diagrams saved before categories stored a confidence number instead. */
function supportOf(el: Element): string | null {
  const support = el.getAttribute("support");
  if (support) return support;
  const raw = el.getAttribute("confidence");
  if (raw === null || raw === "") return null;
  const c = Number(raw);
  return c >= 1 ? "reviewed" : c >= 0.9 ? "stated" : c >= 0.7 ? "derived" : c >= 0.4 ? "implied" : "guess";
}

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

/** The root cell carries the conflicts, open questions and skipped sections as JSON. */
const rootOf = (doc: Document) => doc.querySelector('object[id="0"]');

function listOf<T>(root: Element | null, key: string): T[] {
  try {
    const value = JSON.parse(root?.getAttribute(key) || "[]");
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

/** Everything to review, most serious first. */
export async function findFlags(xml: string): Promise<Flag[]> {
  const doc = await readDoc(xml);
  if (!doc) return [];
  const names = new Map<string, string>();
  doc.querySelectorAll("object, mxCell[id]").forEach((el) => {
    const label = el.getAttribute("label") ?? el.getAttribute("value");
    if (el.getAttribute("id") && label) names.set(el.getAttribute("id")!, toText(label));
  });
  const name = (id: string | null) => (id && names.get(id)) || id || "?";
  // connections are named by their ends; the AI names lanes by id, which the XML prefixes with "lane_"
  const edges = new Map<string, string>();
  doc.querySelectorAll("mxCell[edge='1']").forEach((cell) => {
    const id = cell.getAttribute("id") ?? cell.parentElement?.getAttribute("id");
    if (id) edges.set(id, `${name(cell.getAttribute("source"))} → ${name(cell.getAttribute("target"))}`);
  });
  const anyName = (id: string) => edges.get(id) ?? names.get(id) ?? names.get(`lane_${id}`) ?? id;
  const affects = (ids?: string[]) => (ids?.length ? `Affects: ${ids.map(anyName).join(", ")}` : undefined);

  const flags: Flag[] = [];
  doc.querySelectorAll("object").forEach((o) => {
    const category = supportOf(o);
    const level = category ? LEVEL[category] : undefined;
    if (!level) return;
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
    const sources = o.getAttribute("sources");
    flags.push({ id: o.getAttribute("id") ?? "", kind, label: text, category: category!, level,
                 detail: sources ? `From: ${sources}` : undefined });
  });

  const root = rootOf(doc);
  listOf<Conflict>(root, "conflicts").forEach((c, i) =>
    flags.push({
      id: `conflict:${i}`, kind: "Conflict", category: "sources disagree", level: "red",
      label: c.description,
      detail: [c.resolution && `Drawn: ${c.resolution}`, affects(c.affects)].filter(Boolean).join(" · ") || undefined,
    }));
  listOf<Question>(root, "open_questions").forEach((q, i) =>
    flags.push({
      id: `question:${i}`, kind: "Open question", category: "unanswered", level: "yellow",
      label: q.question,
      detail: [q.source_ref, affects(q.affects)].filter(Boolean).join(" · ") || undefined,
    }));
  return flags.sort((a, b) => ORDER[a.level] - ORDER[b.level]);
}

/** Sections of the sources the AI read and deliberately left out of the diagram. */
export async function findSkipped(xml: string): Promise<Skipped[]> {
  const doc = await readDoc(xml);
  return doc ? listOf<Skipped>(rootOf(doc), "skipped_sections") : [];
}

/** The same diagram with these items reviewed: support "reviewed" (dashed arrows turn solid), or the
 *  conflict / open question removed. */
export async function markReviewed(xml: string, ids: string[]): Promise<string> {
  const doc = await readDoc(xml);
  if (!doc) throw new Error("The diagram could not be read.");
  const wanted = new Set(ids);
  doc.querySelectorAll("object").forEach((o) => {
    if (!wanted.has(o.getAttribute("id") ?? "")) return;
    o.setAttribute("support", "reviewed");
    o.removeAttribute("confidence");
    const cell = o.querySelector("mxCell");
    const style = cell?.getAttribute("style");
    if (cell?.getAttribute("edge") === "1" && style) cell.setAttribute("style", style.replace(/(^|;)dashed=1;?/, "$1"));
  });
  const root = rootOf(doc);
  if (root) {
    for (const [prefix, key] of [["conflict", "conflicts"], ["question", "open_questions"]]) {
      const kept = listOf<unknown>(root, key).filter((_, i) => !wanted.has(`${prefix}:${i}`));
      root.setAttribute(key, JSON.stringify(kept));
    }
  }
  return new XMLSerializer().serializeToString(doc);
}
