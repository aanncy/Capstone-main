import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

export const DRAWIO_URL: string =
  (import.meta.env.VITE_DRAWIO_URL as string | undefined) ?? "http://localhost:8080";
const SRC = `${DRAWIO_URL}/?embed=1&proto=json&spin=1&saveAndExit=0&noSaveBtn=1&noExitBtn=1`;

export type EditorHandle = { exportPng: () => void };
type Props = { xml: string; onChange?: (xml: string) => void };

function download(href: string, name: string) {
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  a.click();
}

/**
 * Embeds the self-hosted draw.io editor in an iframe and talks to it with postMessage (JSON protocol).
 * Flow: draw.io sends {event:"init"} -> we send {action:"load", xml} -> it sends {event:"autosave", xml} on every edit.
 */
const DrawioEditor = forwardRef<EditorHandle, Props>(function DrawioEditor({ xml, onChange }, ref) {
  const frame = useRef<HTMLIFrameElement>(null);
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const [status, setStatus] = useState<"loading" | "ready" | "failed">("loading");

  const post = (msg: object) => frame.current?.contentWindow?.postMessage(JSON.stringify(msg), DRAWIO_URL);

  useImperativeHandle(ref, () => ({
    exportPng: () => post({ action: "export", format: "png", spin: "Exporting" }),
  }));

  // Listen for draw.io events
  useEffect(() => {
    const onMessage = (e: MessageEvent) => {
      if (e.origin !== DRAWIO_URL || e.source !== frame.current?.contentWindow) return;
      if (typeof e.data !== "string") return;
      let msg: { event?: string; xml?: string; data?: string };
      try {
        msg = JSON.parse(e.data);
      } catch {
        return;
      }
      if (msg.event === "init") setStatus("ready");
      else if ((msg.event === "autosave" || msg.event === "save") && msg.xml) onChangeRef.current?.(msg.xml);
      else if (msg.event === "export" && msg.data) download(msg.data, "process-flow.png");
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, []);

  // (Re)load the diagram whenever the editor is ready or a new diagram arrives
  useEffect(() => {
    if (status === "ready") post({ action: "load", xml, autosave: 1 });
  }, [status, xml]);

  // If draw.io never says hello, tell the user how to fix it
  useEffect(() => {
    if (status !== "loading") return;
    const t = setTimeout(() => setStatus((s) => (s === "loading" ? "failed" : s)), 12000);
    return () => clearTimeout(t);
  }, [status]);

  return (
    <div className="editor-frame">
      <iframe ref={frame} src={SRC} title="Diagram editor" />
      {status !== "ready" && (
        <div className="editor-overlay" role="status">
          {status === "loading" ? (
            <p>Starting the editor...</p>
          ) : (
            <div>
              <p><strong>The editor did not start.</strong></p>
              <p>Check that draw.io is running at <code>{DRAWIO_URL}</code>. Start it with <code>docker compose up -d</code>, then reload this page.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
});

export default DrawioEditor;
