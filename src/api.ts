export type Stage = "reading" | "generating" | "checking" | "drawing";
export type GenerateInput = { text: string; files: File[] };

export const STAGES: { id: Stage; label: string; hint: string }[] = [
  { id: "reading", label: "Reading your document", hint: "Extracting the text" },
  { id: "generating", label: "Drafting the process steps", hint: "Finding steps, owners and decisions" },
  { id: "checking", label: "Checking the flow", hint: "Looking for gaps and dead ends" },
  { id: "drawing", label: "Laying out the swimlanes", hint: "Placing each step in its lane" },
];

/**
 * One entry point for the whole pipeline: POST /api/generate (multipart: text, files) and get { xml } back.
 * Several files (an SOP, a transcript, a sketch...) are collated into one diagram.
 * The backend decides which AI model to use; the UI never knows.
 */
export async function generateDiagram(
  input: GenerateInput,
  onStage: (s: Stage) => void
): Promise<{ xml: string }> {
  onStage("reading");
  const body = new FormData();
  body.append("text", input.text);
  for (const f of input.files) body.append("files", f);
  onStage("generating");
  const res = await fetch("/api/generate", { method: "POST", body });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail as string).catch(() => null);
    throw new Error(detail ?? `The server returned an error (${res.status}).`);
  }
  onStage("drawing");
  return (await res.json()) as { xml: string };
}

/**
 * Apply a change described in plain words to the diagram currently in the editor.
 * POST /api/amend with the editor's XML (so manual edits are kept) and get the new XML back.
 */
export async function amendDiagram(xml: string, instruction: string): Promise<{ xml: string }> {
  const res = await fetch("/api/amend", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ xml, instruction }),
  });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail as string).catch(() => null);
    throw new Error(detail ?? `The server returned an error (${res.status}).`);
  }
  return (await res.json()) as { xml: string };
}
