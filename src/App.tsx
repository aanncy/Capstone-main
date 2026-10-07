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
    setStage("reading");
    setScreen("progress");
    try {
      const result = await generateDiagram(input, setStage);
      setXml(result.xml);
      setScreen("editor");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    }
  };

  return (
    <div className="shell">
      <header className="topbar">
        <span className="brand">Process Flow Tool</span>
      </header>
      {screen === "input" && <InputPage onGenerate={run} />}
      {screen === "progress" && (
        <ProgressPage
          stage={stage}
          error={error}
          onRetry={() => last.current && run(last.current)}
          onBack={() => setScreen("input")}
        />
      )}
      {screen === "editor" && <EditorPage xml={xml} onNew={() => setScreen("input")} />}
    </div>
  );
}
