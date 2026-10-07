# Process Flow Tool: frontend

React + TypeScript (Vite) frontend with a self-hosted draw.io editor embedded in the page.
It runs on its own with a built-in sample diagram, so you can build and test the UI before the backend exists.

## Run it

```bash
docker compose up -d        # starts draw.io on http://localhost:8080
cp .env.example .env
npm install
npm run dev                 # opens on http://localhost:5173
```

Click **Use an example**, then **Create diagram**. You should see the progress lanes, then the swimlane diagram in the editor.

## Week-1 spike checklist (does the draw.io round trip work?)

1. The diagram loads with three lanes and six steps.
2. Edit a step label, drag a step into a different lane, add a new shape. Does it stay inside the lane?
3. Watch the **Steps to check** panel. It lists steps under 70% confidence, read from the XML draw.io sends back.
   If the list still shows the right steps and percentages after you edit, custom attributes (`source_ref`, `confidence`) survive editing.
4. Rename a low-confidence step. The panel should show the new name with the same percentage.
5. Click **Export PNG** and **Save as .drawio**. Open the .drawio file at your draw.io site to confirm it loads.
6. If the panel breaks, open the browser console and inspect the XML in the `autosave` message. Compressed XML would need
   draw.io's `compressXml` option turned off (check the current embed docs).

Record the results. If steps 2 to 4 fail, tell the team before anyone builds on draw.io.

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | Self-hosted draw.io container |
| `src/App.tsx` | Screen flow: input, progress, editor |
| `src/pages.tsx` | The three pages |
| `src/DrawioEditor.tsx` | draw.io iframe and postMessage handling |
| `src/api.ts` | `generateDiagram()`: mock now, backend later |
| `src/sampleDiagram.ts` | Hand-written swimlane XML used as the pattern for the converter |
| `src/xmlUtils.ts` | Reads steps and custom fields back out of draw.io XML |

## Connecting the backend later

Set `VITE_USE_MOCK=false`. The app then calls `POST /api/generate` (multipart form: `text`, `file`) and expects `{ "xml": "<mxfile>..." }`.
Vite proxies `/api` to `http://localhost:8000`. The backend handles Copilot, validation and layout. If you prefer to run the
JSON-to-XML converter in the browser, have the backend return JSON instead and convert it inside `generateDiagram()`.

## Notes

- The draw.io messages used (`init`, `load`, `autosave`, `export`) are from memory of its embed protocol.
  Check them against the current draw.io embed documentation during the spike.
- The "Apply change" button is a placeholder until the refinement task.
- Pin the draw.io image version in `docker-compose.yml` before the demo.
