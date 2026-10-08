import { useCallback, useRef, useState } from "react";
import type { DragEvent } from "react";

import DrawioEditor from "./DrawioEditor";
import type { EditorHandle } from "./DrawioEditor";

import { STAGES } from "./api";
import type { GenerateInput, Stage } from "./api";

import { SAMPLE_TEXT } from "./sampleDiagram";

/* ---------------------------------------------------------------- Input */

export function InputPage({
  onGenerate,
}: {
  onGenerate: (i: GenerateInput) => void;
}) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [over, setOver] = useState(false);

  const canSubmit =
    text.trim().length > 0 || file !== null;

  const onDrop = (
    e: DragEvent<HTMLLabelElement>
  ) => {
    e.preventDefault();
    setOver(false);

    const f = e.dataTransfer.files?.[0];

    if (f) {
      setFile(f);
    }
  };

  return (
    <div className="input-page">
      {/* HERO */}
      <section className="hero">
        <div className="hero-eyebrow">
          UOB AI PRODUCTIVITY
        </div>

        <h1>
          Turn ideas into
          <br />
          <span className="accent">
            editable diagrams.
          </span>
        </h1>

        <p className="hero-copy">
          Convert process descriptions, documents,
          screenshots and images into structured
          draw.io diagrams you can continue editing.
        </p>
      </section>

      {/* TEXT */}
      <section className="flow-section alt">
        <div className="flow-inner">
          <span className="section-number">
            01 · DESCRIBE
          </span>

          <h2 className="section-title">
            Start with your process.
          </h2>

          <p className="section-copy">
            Tell us what happens, who is involved and
            where decisions are made. Your notes do not
            need to be perfectly formatted.
          </p>

          <div className="textarea-shell">
            <div className="textarea-head">
              <label
                className="field-label"
                htmlFor="process-text"
              >
                Process description
              </label>

              <button
                type="button"
                className="example-link"
                onClick={() =>
                  setText(SAMPLE_TEXT)
                }
              >
                Use an example
              </button>
            </div>

            <textarea
              id="process-text"
              value={text}
              onChange={(e) =>
                setText(e.target.value)
              }
              placeholder="For example: A customer submits a request. The service team reviews it and sends it to a manager for approval..."
              rows={8}
            />
          </div>
        </div>
      </section>

      {/* UPLOAD */}
      <section className="flow-section">
        <div className="flow-inner">
          <span className="section-number">
            02 · UPLOAD
          </span>

          <h2 className="section-title">
            Or show us what you already have.
          </h2>

          <p className="section-copy">
            Upload a document, screenshot or image and
            we will interpret the process structure for
            you.
          </p>

          <label
            className={`drop${
              over ? " over" : ""
            }`}
            onDragOver={(e) => {
              e.preventDefault();
              setOver(true);
            }}
            onDragLeave={() =>
              setOver(false)
            }
            onDrop={onDrop}
          >
            <input
              type="file"
              accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg"
              onChange={(e) =>
                setFile(
                  e.target.files?.[0] ??
                    null
                )
              }
            />

            <div className="upload-icon">
              ↑
            </div>

            {file ? (
              <>
                <div className="upload-title">
                  {file.name}
                </div>

                <p className="upload-copy">
                  {Math.max(
                    1,
                    Math.round(
                      file.size / 1024
                    )
                  )}{" "}
                  KB
                </p>

                <span className="upload-types">
                  READY TO USE
                </span>
              </>
            ) : (
              <>
                <div className="upload-title">
                  Upload a file
                </div>

                <p className="upload-copy">
                  Drag and drop here, or
                  click to browse
                </p>

                <span className="upload-types">
                  PDF · DOCX · TXT · MD · PNG · JPG
                </span>
              </>
            )}
          </label>

          {file && (
            <button
              type="button"
              className="remove-file"
              onClick={() =>
                setFile(null)
              }
            >
              Remove file
            </button>
          )}
        </div>
      </section>

      {/* GENERATE */}
      <section className="flow-section generate-section">
        <div className="flow-inner">
          <span className="section-number">
            03 · GENERATE
          </span>

          <h2 className="section-title">
            Ready when you are.
          </h2>

          <p className="section-copy">
            We will interpret your content, identify
            the important process steps and build an
            editable draw.io diagram.
          </p>

          <div className="generate-wrap">
            <button
              type="button"
              className="primary generate-button"
              disabled={!canSubmit}
              onClick={() =>
                onGenerate({
                  text,
                  file,
                })
              }
            >
              Generate diagram
              <span aria-hidden="true">
                →
              </span>
            </button>

            {!canSubmit && (
              <span className="generate-hint">
                Add a description or
                upload a file to continue.
              </span>
            )}
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
              src="/uob-logo.png"
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

  const [latest, setLatest] =
    useState(xml);

  const handleChange =
    useCallback((x: string) => {
      setLatest(x);
    }, []);

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

        {/* IMPORTANT:
            Do not wrap DrawioEditor in .editor-frame.
            The DrawioEditor component needs to receive
            the available flex height directly.
        */}
        <DrawioEditor
          ref={editor}
          xml={xml}
          onChange={handleChange}
        />
      </div>
    </div>
  );
}