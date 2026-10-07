import { useCallback, useRef, useState } from "react";
import type { DragEvent } from "react";
import DrawioEditor from "./DrawioEditor";
import type { EditorHandle } from "./DrawioEditor";
import { STAGES } from "./api";
import type { GenerateInput, Stage } from "./api";
import { SAMPLE_TEXT } from "./sampleDiagram";
import { parseNodes } from "./xmlUtils";

/* ---------------------------------------------------------------- Input */
export function InputPage({ onGenerate }: { onGenerate: (i: GenerateInput) => void }) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);
  const canSubmit = text.trim().length > 0 || file !== null;

  const onDrop = (e: DragEvent<HTMLLabelElement>) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setFile(f);
  };

  return (
    <main className="page">
      <h1>Turn a process description into a swimlane diagram</h1>
      <p className="lede">Paste your process notes or upload a document. You can edit the diagram once it is drawn.</p>

      <label className="field-label" htmlFor="process-text">Process description</label>
      <textarea
        id="process-text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Describe who does what, in what order, and where decisions are made."
        rows={9}
      />
      <button type="button" className="link" onClick={() => setText(SAMPLE_TEXT)}>Use an example</button>

      <label
        className={`drop${over ? " over" : ""}`}
        onDragOver={(e) => { e.preventDefault(); setOver(true); }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        <input
          type="file"
          accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        {file ? (
          <span><strong>{file.name}</strong> ({Math.max(1, Math.round(file.size / 1024))} KB)</span>
        ) : (
          <span>Drop a PDF, Word, text or image file here, or <u>choose a file</u></span>
        )}
      </label>
      {file && <button type="button" className="link" onClick={() => setFile(null)}>Remove file</button>}

      <div className="actions">
        <button type="button" className="primary" disabled={!canSubmit} onClick={() => onGenerate({ text, file })}>
          Create diagram
        </button>
        {!canSubmit && <span className="hint">Add a description or a file to continue.</span>}
      </div>
    </main>
  );
}

/* ---------------------------------------------------------------- Progress */
export function ProgressPage({
  stage, error, onRetry, onBack,
}: { stage: Stage; error: string | null; onRetry: () => void; onBack: () => void }) {
  const current = STAGES.findIndex((s) => s.id === stage);
  return (
    <main className="page">
      <h1>{error ? "The diagram could not be created" : "Creating your diagram"}</h1>
      {error ? (
        <div className="error" role="alert">
          <p>{error}</p>
          <p>Try again, or go back and change your input.</p>
          <div className="actions">
            <button type="button" className="primary" onClick={onRetry}>Try again</button>
            <button type="button" className="secondary" onClick={onBack}>Change input</button>
          </div>
        </div>
      ) : (
        <ol className="lanes" aria-live="polite">
          {STAGES.map((s, i) => {
            const state = i < current ? "done" : i === current ? "active" : "todo";
            return (
              <li key={s.id} className={`lane ${state}`}>
                <span className="lane-head" aria-hidden="true" />
                <div className="lane-body">
                  <span className="lane-title">{s.label}</span>
                  <span className="lane-hint">{state === "done" ? "Done" : s.hint}</span>
                  <span className="lane-bar" aria-hidden="true" />
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </main>
  );
}

/* ---------------------------------------------------------------- Editor */
export function EditorPage({ xml, onNew }: { xml: string; onNew: () => void }) {
  const editor = useRef<EditorHandle>(null);
  const [latest, setLatest] = useState(xml);
  const handleChange = useCallback((x: string) => setLatest(x), []);
  const [request, setRequest] = useState("");

  const toCheck = parseNodes(latest).filter((n) => n.confidence !== undefined && n.confidence < 0.7);

  const saveFile = () => {
    const url = URL.createObjectURL(new Blob([latest], { type: "application/xml" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "process-flow.drawio";
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="editor-layout">
      <div className="editor-main">
        <div className="toolbar">
          <button type="button" className="secondary" onClick={onNew}>New diagram</button>
          <span className="spacer" />
          <button type="button" className="secondary" onClick={saveFile}>Save as .drawio</button>
          <button type="button" className="primary" onClick={() => editor.current?.exportPng()}>Export PNG</button>
        </div>
        <DrawioEditor ref={editor} xml={xml} onChange={handleChange} />
      </div>

      <aside className="side" aria-label="Review and changes">
        <section>
          <h2>Steps to check</h2>
          {toCheck.length === 0 ? (
            <p className="muted">No uncertain steps. Every step was read with high confidence.</p>
          ) : (
            <ul className="check-list">
              {toCheck.map((n) => (
                <li key={n.id}>
                  <strong>{n.label}</strong>
                  <span className="muted">
                    {Math.round((n.confidence ?? 0) * 100)}% sure{n.sourceRef ? ` · from ${n.sourceRef}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section>
          <h2>Ask for changes</h2>
          <label className="field-label" htmlFor="change-request">Describe the change</label>
          <textarea
            id="change-request"
            rows={4}
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            placeholder="For example: add an approval step after the document review."
          />
          <button type="button" className="primary" disabled title="Connects to the backend in the refinement task">
            Apply change
          </button>
          <p className="hint">Not connected yet. This needs the backend refinement step.</p>
        </section>
      </aside>
    </div>
  );
}
