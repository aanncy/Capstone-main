import { SAMPLE_XML } from "./sampleDiagram";

export type Stage = "reading" | "generating" | "checking" | "drawing";
export type GenerateInput = { text: string; file: File | null };

export const STAGES: { id: Stage; label: string; hint: string }[] = [
  { id: "reading", label: "Reading your document", hint: "Extracting the text" },
  { id: "generating", label: "Drafting the process steps", hint: "Finding steps, owners and decisions" },
  { id: "checking", label: "Checking the flow", hint: "Looking for gaps and dead ends" },
  { id: "drawing", label: "Laying out the swimlanes", hint: "Placing each step in its lane" },
];

const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/**
 * One entry point for the whole pipeline.
 * Mock mode: plays the stages and returns the sample diagram.
 * Real mode: POST /api/generate (multipart: text, file) and expect { xml: string } back.
 * The backend decides how to reach Copilot; the UI never knows.
 */
export async function generateDiagram(
  input: GenerateInput,
  onStage: (s: Stage) => void
): Promise<{ xml: string }> {
  if (USE_MOCK) {
    for (const s of STAGES) {
      onStage(s.id);
      await sleep(1100);
    }
    return { xml: SAMPLE_XML };
  }
  onStage("reading");
  const body = new FormData();
  body.append("text", input.text);
  if (input.file) body.append("file", input.file);
  onStage("generating");
  const res = await fetch("/api/generate", { method: "POST", body });
  if (!res.ok) {
    const detail = await res.json().then((j) => j.detail as string).catch(() => null);
    throw new Error(detail ?? `The server returned an error (${res.status}).`);
  }
  onStage("drawing");
  return (await res.json()) as { xml: string };
}
