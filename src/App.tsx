import { useRef, useState } from "react";
import { generateDiagram } from "./api";
import type { GenerateInput, Stage } from "./api";
import { EditorPage, InputPage, ProgressPage } from "./pages";

type Screen = "input" | "progress" | "editor";

export default function App() {
  const [screen, setScreen] = useState<Screen>("input");
  const [stage, setStage] = useState<Stage>("reading");
  const [error, setError] = useState<string | null>(null);
  const [xml, setXml] = useState("");

  const last = useRef<GenerateInput | null>(null);

  const run = async (input: GenerateInput) => {
    last.current = input;

    setError(null);
    setXml("");
    setStage("reading");
    setScreen("progress");

    try {
      const result = await generateDiagram(input, setStage);

      setXml(result.xml);
      setScreen("editor");
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "Something went wrong while creating your diagram."
      );
    }
  };

  const startNew = () => {
    setXml("");
    setError(null);
    setStage("reading");
    last.current = null;
    setScreen("input");
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand-wrap">
            <img
              src="/UOB_Logo_(2022).svg"
              alt="UOB"
              className="brand-logo"
            />

            <span
              className="brand-divider"
              aria-hidden="true"
            />

            <span className="brand-subtitle">
              FLOW
            </span>
          </div>

          <span className="topbar-note">
          </span>
        </div>
      </header>

      <main className="app-main">
        {screen === "input" && (
          <InputPage onGenerate={run} />
        )}

        {screen === "progress" && (
          <ProgressPage
            stage={stage}
            error={error}
            onRetry={() => {
              if (last.current) {
                run(last.current);
              }
            }}
            onBack={() => setScreen("input")}
          />
        )}

        {screen === "editor" && (
          <EditorPage
            xml={xml}
            onNew={startNew}
          />
        )}
      </main>
    </div>
  );
}