import { useCallback, useEffect, useRef, useState } from "react";
import type { DragEvent } from "react";

import DrawioEditor from "./DrawioEditor";
import type { EditorHandle } from "./DrawioEditor";

import { STAGES, amendDiagram } from "./api";
import { findFlags, findSkipped, markReviewed } from "./review";
import type { Flag, Skipped } from "./review";
import type { GenerateInput, Stage } from "./api";

import { SAMPLE_TEXT } from "./sampleDiagram";

/* ---------------------------------------------------------------- Input */

// match the backend (backend/app/extract.py): one request carries all files to the AI
const MAX_FILES = 10;
const MAX_TOTAL_MB = 14;
const MAX_TOTAL_BYTES = MAX_TOTAL_MB * 1024 * 1024;

const formatSize = (bytes: number) =>
  bytes >= 1024 * 1024
    ? `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;

export function InputPage({
  onGenerate,
}: {
  onGenerate: (i: GenerateInput) => void;
}) {
  const [text, setText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [over, setOver] = useState(false);

  const canSubmit =
    text.trim().length > 0 || files.length > 0;

  // several sources about one process (an SOP, a meeting transcript, a rough diagram...) are collated into one diagram
  const addFiles = (list: FileList | null) => {
    if (!list) return;
    // FileList belongs to the input/drop event. Snapshot it before the input
    // is reset: React may run the state updater after that reset clears it.
    const incoming = Array.from(list);

    setFiles((current) => {
      const seen = new Set(current.map((f) => `${f.name}/${f.size}`));
      const added = incoming.filter((f) => {
        const key = `${f.name}/${f.size}`;
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      });

      return [...current, ...added].slice(0, MAX_FILES);
    });
  };

  const totalBytes =
    files.reduce((sum, f) => sum + f.size, 0);

  const tooBig =
    totalBytes > MAX_TOTAL_BYTES;

  const onDrop = (
    e: DragEvent<HTMLLabelElement>
  ) => {
    e.preventDefault();
    setOver(false);
    addFiles(e.dataTransfer.files);
  };

  return (
    <div className="input-page">
      <section className="hero">
        <h1>
          Turn in-house documentation into
          <br />
          <span className="accent">editable diagrams.</span>
        </h1>

        <p className="hero-copy">
          Convert process notes and documents into editable draw.io diagrams.
        </p>
      </section>

      <section className="creation-section">
        <div className="creation-inner">
          <div className="textarea-shell">
            <div className="textarea-head">
              <label className="field-label" htmlFor="process-text">
                Process description
              </label>

              <button
                type="button"
                className="example-link"
                onClick={() => setText(SAMPLE_TEXT)}
              >
                Use an example
              </button>
            </div>

            <textarea
              id="process-text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Describe the process, the people involved, and any decisions or outcomes."
              rows={8}
            />
          </div>

          <div className="upload-area">
            <h2>Or upload documents</h2>

            <label
              className={`drop${over ? " over" : ""}`}
              onDragOver={(e) => {
                e.preventDefault();
                setOver(true);
              }}
              onDragLeave={() => setOver(false)}
              onDrop={onDrop}
            >
              <input
                type="file"
                multiple
                accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg,.webp"
                onChange={(e) => {
                  addFiles(e.target.files);
                  e.target.value = ""; // so the same file can be picked again after removing it
                }}
              />

              <div className="upload-icon">↑</div>

              <div className="upload-title">
                {files.length ? "Add more files" : "Choose files or drop them here"}
              </div>

              <p className="upload-copy">
                PDF · DOCX · TXT · MD · PNG · JPG · up to {MAX_FILES} files, {MAX_TOTAL_MB} MB in total
              </p>
            </label>

            {files.length > 0 && (
              <ul className="file-list">
                {files.map((f, i) => (
                  <li key={`${f.name}/${f.size}`}>
                    <span className="file-name">{f.name}</span>

                    <span className="file-size">
                      {formatSize(f.size)}
                    </span>

                    <button
                      type="button"
                      className="file-remove"
                      aria-label={`Remove ${f.name}`}
                      onClick={() => setFiles((current) => current.filter((_, j) => j !== i))}
                    >
                      ×
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {files.length > 1 && !tooBig && (
              <p className="upload-note">
                These {files.length} files will be combined into one diagram.
              </p>
            )}

            {tooBig && (
              <p className="upload-note err" role="alert">
                The files add up to {formatSize(totalBytes)}. Together they must stay under {MAX_TOTAL_MB} MB.
              </p>
            )}
          </div>

          <div className="create-actions">
            <button
              type="button"
              className="primary generate-button"
              disabled={!canSubmit || tooBig}
              onClick={() => onGenerate({ text, files })}
            >
              Generate diagram
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}

/* ---------------------------------------------------------------- Progress */

export function ProgressPage({
  stage,
  error,
  onRetry,
  onBack,
}: {
  stage: Stage;
  error: string | null;
  onRetry: () => void;
  onBack: () => void;
}) {
  const current = STAGES.findIndex(
    (s) => s.id === stage
  );

  return (
    <main className="progress-page">
      <div className="progress-card">
        {!error && (
          <div className="progress-logo-wrap">
            <img
              src="/UOB_Logo_(2022).svg"
              alt="UOB"
              className="progress-logo"
            />
          </div>
        )}

        <h1>
          {error
            ? "The diagram could not be created"
            : "Building your diagram"}
        </h1>

        {!error && (
          <p className="progress-copy">
            We are reading your content and
            turning it into a structured,
            editable process diagram.
          </p>
        )}

        {error ? (
          <div
            className="error"
            role="alert"
          >
            <p>{error}</p>

            <p>
              Try again, or go back and
              change your input.
            </p>

            <div className="actions">
              <button
                type="button"
                className="primary"
                onClick={onRetry}
              >
                Try again
              </button>

              <button
                type="button"
                className="secondary"
                onClick={onBack}
              >
                Change input
              </button>
            </div>
          </div>
        ) : (
          <ol
            className="lanes"
            aria-live="polite"
          >
            {STAGES.map((s, i) => {
              const state =
                i < current
                  ? "done"
                  : i === current
                    ? "active"
                    : "todo";

              const statusText =
                state === "done"
                  ? "Done"
                  : s.hint;

              return (
                <li
                  key={s.id}
                  className={`lane ${state}`}
                >
                  <span
                    className="lane-head"
                    aria-hidden="true"
                  />

                  <div className="lane-body">
                    <div className="lane-row">
                      <span className="lane-title">
                        {s.label}
                      </span>

                      <span
                        className={`lane-status ${state}`}
                      >
                        {statusText}
                      </span>
                    </div>

                    <span
                      className="lane-bar"
                      aria-hidden="true"
                    />
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </main>
  );
}

/* ---------------------------------------------------------------- Editor */

export function EditorPage({
  xml,
  onNew,
}: {
  xml: string;
  onNew: () => void;
}) {
  const editor =
    useRef<EditorHandle>(null);

  // what is loaded into draw.io (changes when an amendment comes back)
  const [shown, setShown] =
    useState(xml);

  // what draw.io last reported, including the user's own edits
  const [latest, setLatest] =
    useState(xml);

  const handleChange =
    useCallback((x: string) => {
      setLatest(x);
    }, []);

  // what needs review (weakly supported items, conflicts, open questions), kept in step with the editor
  const [flags, setFlags] =
    useState<Flag[]>([]);

  const [skipped, setSkipped] =
    useState<Skipped[]>([]);

  useEffect(() => {
    let current = true;

    findFlags(latest).then((f) => {
      if (current) setFlags(f);
    });

    findSkipped(latest).then((s) => {
      if (current) setSkipped(s);
    });

    return () => {
      current = false;
    };
  }, [latest]);

  const clearFlags = async (ids: string[]) => {
    const reviewed =
      await markReviewed(
        latest,
        ids
      );

    setShown(reviewed);
    setLatest(reviewed);
  };

  const saveFile = () => {
    const url =
      URL.createObjectURL(
        new Blob([latest], {
          type: "application/xml",
        })
      );

    const a =
      document.createElement("a");

    a.href = url;
    a.download =
      "process-flow.drawio";

    a.click();

    URL.revokeObjectURL(url);
  };

  return (
    <div className="editor-layout">
      <div className="editor-main">
        <div className="toolbar">
          <button
            type="button"
            className="secondary"
            onClick={onNew}
          >
            ← New diagram
          </button>

          <span className="spacer" />

          <button
            type="button"
            className="secondary"
            onClick={saveFile}
          >
            Save .drawio
          </button>

          <button
            type="button"
            className="primary"
            onClick={() =>
              editor.current?.exportPng()
            }
          >
            Export PNG
          </button>
        </div>

        <div className="editor-body">
          {/* IMPORTANT:
              Do not wrap DrawioEditor in .editor-frame.
              The DrawioEditor component needs to receive
              the available flex height directly.
          */}
          <DrawioEditor
            ref={editor}
            xml={shown}
            onChange={handleChange}
          />

          <AmendPanel
            flags={flags}
            skipped={skipped}
            onClearFlags={clearFlags}
            onApply={async (instruction) => {
              const result =
                await amendDiagram(
                  latest,
                  instruction
                );

              setShown(result.xml);
              setLatest(result.xml);
            }}
          />
        </div>
      </div>
    </div>
  );
}

/**
 * Collapsible side panel: the user describes a change in plain words,
 * the AI applies it, and the new diagram replaces the one in the editor.
 * Starts open.
 */
function AmendPanel({
  flags,
  skipped,
  onClearFlags,
  onApply,
}: {
  flags: Flag[];
  skipped: Skipped[];
  onClearFlags: (ids: string[]) => Promise<void>;
  onApply: (instruction: string) => Promise<void>;
}) {
  const [open, setOpen] =
    useState(true);

  const [text, setText] =
    useState("");

  const [busy, setBusy] =
    useState(false);

  const [error, setError] =
    useState<string | null>(null);

  const [done, setDone] =
    useState<string | null>(null);

  const [clearing, setClearing] =
    useState(false);

  const clear = async (ids: string[]) => {
    if (clearing || busy || ids.length === 0) return;

    setClearing(true);
    setError(null);

    try {
      await onClearFlags(ids);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Could not mark the items as reviewed."
      );
    } finally {
      setClearing(false);
    }
  };

  const apply = async () => {
    const instruction = text.trim();

    if (!instruction || busy) return;

    setBusy(true);
    setError(null);
    setDone(null);

    try {
      await onApply(instruction);

      setDone(instruction);
      setText("");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Something went wrong while changing your diagram."
      );
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return (
      <aside className="amend-panel collapsed">
        <button
          type="button"
          className="amend-toggle"
          onClick={() => setOpen(true)}
          aria-label="Open the amend diagram panel"
          aria-expanded={false}
        >
          ‹
        </button>

        <span className="amend-collapsed-label">
          Amend diagram
        </span>
      </aside>
    );
  }

  return (
    <aside className="amend-panel">
      <div className="amend-head">
        <h2>Amend diagram</h2>

        <button
          type="button"
          className="amend-toggle"
          onClick={() => setOpen(false)}
          aria-label="Collapse the amend diagram panel"
          aria-expanded={true}
        >
          ›
        </button>
      </div>

      <div className="amend-body">
        <ReviewList
          flags={flags}
          skipped={skipped}
          disabled={busy || clearing}
          onClear={clear}
        />

        <label
          htmlFor="amend-text"
          className="amend-label"
        >
          Describe the change
        </label>

        <textarea
          id="amend-text"
          className="amend-text"
          placeholder="For example: Add a compliance review after approval."
          value={text}
          disabled={busy}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              apply();
            }
          }}
        />

        <button
          type="button"
          className="primary amend-apply"
          disabled={!text.trim() || busy}
          onClick={apply}
        >
          {busy ? "Applying change..." : "Apply change"}
        </button>

        {busy && (
          <div
            className="amend-loading-line"
            role="progressbar"
            aria-label="Updating diagram"
            aria-valuetext="The AI is updating your diagram"
          >
            <span />
          </div>
        )}

        <p className="amend-hint">
          Press Ctrl/⌘ + Enter to apply. Edits you made in the editor are kept, but the layout is redrawn.
        </p>

        {busy && (
          <p className="amend-status" role="status">
            The AI is updating your diagram. This may take a few minutes.
          </p>
        )}

        {done && !busy && (
          <p className="amend-status ok" role="status">
            Applied: “{done}”
          </p>
        )}

        {error && (
          <p className="amend-status err" role="alert">
            {error}
          </p>
        )}
      </div>
    </aside>
  );
}

/**
 * What a person should check before the diagram is used:
 * - steps, lanes and connections the AI classified as "guess" (red) or "implied" (yellow);
 * - places where the sources disagree (red) and questions the sources leave open (yellow).
 * The tick on an item marks just that one as reviewed; "Mark all as reviewed" does every item.
 * Below the list, the sections of the sources the AI read but left out on purpose.
 */
function ReviewList({
  flags,
  skipped,
  disabled,
  onClear,
}: {
  flags: Flag[];
  skipped: Skipped[];
  disabled: boolean;
  onClear: (ids: string[]) => void;
}) {
  const red =
    flags.filter((f) => f.level === "red").length;

  return (
    <section
      className="review"
      aria-labelledby="review-title"
    >
      <div className="review-head">
        <span
          id="review-title"
          className="amend-label"
        >
          Needs review
        </span>

        {flags.length > 0 && (
          <span className="review-count">
            {flags.length}
            {red > 0 && ` (${red} urgent)`}
          </span>
        )}
      </div>

      {flags.length === 0 ? (
        <p className="review-empty">
          Nothing to review: no guessed or implied items, conflicts or open questions.
        </p>
      ) : (
        <>
          <ul className="review-list">
            {flags.map((f) => (
              <li
                key={f.id}
                className={`review-item ${f.level}`}
              >
                <span className="review-text">
                  <span className="review-label">
                    {f.label}
                  </span>

                  {f.detail && (
                    <span className="review-detail">
                      {f.detail}
                    </span>
                  )}

                  <span className="review-meta">
                    {f.kind} · {f.category}
                  </span>
                </span>

                <button
                  type="button"
                  className="review-tick"
                  disabled={disabled}
                  onClick={() => onClear([f.id])}
                  aria-label={`Mark ${f.kind.toLowerCase()} "${f.label}" as reviewed`}
                  title="Mark as reviewed"
                >
                  ✓
                </button>
              </li>
            ))}
          </ul>

          <button
            type="button"
            className="secondary review-clear"
            disabled={disabled}
            onClick={() => onClear(flags.map((f) => f.id))}
          >
            Mark all as reviewed
          </button>
        </>
      )}

      {skipped.length > 0 && (
        <details className="review-skipped">
          <summary>
            Left out on purpose ({skipped.length})
          </summary>

          <ul>
            {skipped.map((x, i) => (
              <li key={i}>
                <strong>{x.section}</strong>
                {x.source && ` (${x.source})`}
                {x.reason && `: ${x.reason}`}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
