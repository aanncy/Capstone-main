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
  area?: Box; // where it is in the diagram, framed for viewing (the editor zooms to it on click)
};

export type Box = { x: number; y: number; width: number; height: number };

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

const num = (v: string | null | undefined, d = 0) => (v == null || v === "" || isNaN(Number(v)) ? d : Number(v));

/** Where every lane, step and connection is, in diagram coordinates (steps sit inside lanes, so add the lane's
 *  position). A connection's box covers its whole line: both ends and every bend. */
function locate(doc: Document): Map<string, Box> {
  const cells = new Map<string, { cell: Element; id: string }>();
  doc.querySelectorAll("mxCell").forEach((cell) => {
    const id = cell.getAttribute("id") ?? cell.parentElement?.getAttribute("id");
    if (id) cells.set(id, { cell, id });
  });
  const boxes = new Map<string, Box>();
  const vertexBox = (id: string, depth = 0): Box | undefined => {
    if (boxes.has(id)) return boxes.get(id);
    const entry = cells.get(id);
    const g = entry?.cell.querySelector(":scope > mxGeometry");
    if (!entry || entry.cell.getAttribute("vertex") !== "1" || !g || depth > 10) return undefined;
    const box = { x: num(g.getAttribute("x")), y: num(g.getAttribute("y")),
                  width: num(g.getAttribute("width")), height: num(g.getAttribute("height")) };
    const parent = vertexBox(entry.cell.getAttribute("parent") ?? "", depth + 1);
    if (parent) { box.x += parent.x; box.y += parent.y; }
    boxes.set(id, box);
    return box;
  };
  cells.forEach((_, id) => vertexBox(id));
  cells.forEach(({ cell }, id) => {
    if (cell.getAttribute("edge") !== "1") return;
    const style = Object.fromEntries((cell.getAttribute("style") ?? "").split(";").filter((kv) => kv.includes("="))
      .map((kv) => kv.split("=", 2)));
    const end = (cellId: string | null, fx?: string, fy?: string) => {
      const b = cellId ? boxes.get(cellId) : undefined;
      return b ? [b.x + b.width * num(fx, 0.5), b.y + b.height * num(fy, 0.5)] : undefined;
    };
    const pts = [end(cell.getAttribute("source"), style.exitX, style.exitY),
                 ...Array.from(cell.querySelectorAll("Array[as='points'] > mxPoint"))
                   .map((p) => [num(p.getAttribute("x")), num(p.getAttribute("y"))]),
                 end(cell.getAttribute("target"), style.entryX, style.entryY)].filter(Boolean) as number[][];
    if (pts.length) boxes.set(id, union(pts.map(([x, y]) => ({ x, y, width: 0, height: 0 })))!);
  });
  return boxes;
}

function union(list: Box[]): Box | undefined {
  if (!list.length) return undefined;
  const x = Math.min(...list.map((b) => b.x)), y = Math.min(...list.map((b) => b.y));
  const r = Math.max(...list.map((b) => b.x + b.width)), btm = Math.max(...list.map((b) => b.y + b.height));
  return { x, y, width: r - x, height: btm - y };
}

/** Show at least this much around an item, so a small step is seen in context rather than blown up. */
function framed(b: Box | undefined, minW = 720, minH = 420): Box | undefined {
  if (!b) return undefined;
  const width = Math.max(b.width, minW), height = Math.max(b.height, minH);
  return { x: b.x - (width - b.width) / 2, y: b.y - (height - b.height) / 2, width, height };
}

/** Everything to review, most serious first. */
export async function findFlags(xml: string): Promise<Flag[]> {
  const doc = await readDoc(xml);
  if (!doc) return [];
  const where = locate(doc);
  // a lane can be thousands of pixels long: show its start, where its name is
  const laneStart = (b: Box) => ({ ...b, width: Math.min(b.width, 1400) });
  const areaOf = (ids: string[]) => framed(union(ids.map((id) => {
    const lane = where.get(id.startsWith("lane_") ? id : `lane_${id}`);
    return lane ? laneStart(lane) : where.get(id);
  }).filter(Boolean) as Box[]));
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
    const id = o.getAttribute("id") ?? "";
    const box = where.get(id);
    flags.push({ id, kind, label: text, category: category!, level,
                 detail: sources ? `From: ${sources}` : undefined,
                 area: framed(kind === "Lane" && box ? laneStart(box) : box) });
  });

  const root = rootOf(doc);
  listOf<Conflict>(root, "conflicts").forEach((c, i) =>
    flags.push({
      id: `conflict:${i}`, kind: "Conflict", category: "sources disagree", level: "red",
      label: c.description,
      area: areaOf(c.affects ?? []),
      detail: [c.resolution && `Drawn: ${c.resolution}`, affects(c.affects)].filter(Boolean).join(" · ") || undefined,
    }));
  listOf<Question>(root, "open_questions").forEach((q, i) =>
    flags.push({
      id: `question:${i}`, kind: "Open question", category: "unanswered", level: "yellow",
      label: q.question,
      area: areaOf(q.affects ?? []),
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
