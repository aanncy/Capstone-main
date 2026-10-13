# UOB AI Diagram Builder

Turns process documentation (an SOP, a policy, a transcript, notes) into an editable **swimlane flow diagram**.
An AI model reads the document and drafts the process as structured data; the backend checks it, lays it out
and sends it to a draw.io editor in the browser, where people review, amend and export it.

## Using the app

1. **Create.** Paste a description, upload a file (`.pdf`, `.docx`, `.txt`, `.md`, `.png`, `.jpg`, `.webp`, up to 14 MB),
   or both, and click **Create diagram**. Long documents take a minute or two.
2. **Review.** The diagram opens in the draw.io editor. Each lane has its own colour and its name repeats along the lane.
   The **Needs review** list (right-hand panel) shows the steps, lanes and connections the AI was unsure about:
   **yellow** for confidence 40 to 69 %, **red** below 40 %. Unsure connections are also drawn **dashed**.
   Check each one, then click its **✓** (or **Mark all as reviewed**): its confidence becomes 100 % and it leaves the list.
3. **Amend.** Under **Describe the change**, type what to change in plain words (for example "Add a compliance
   review after approval") and click **Apply change** (or Ctrl/⌘ + Enter). Your own edits in the editor are kept;
   the layout is redrawn.
4. **Edit by hand** with the normal draw.io tools at any time.
5. **Save .drawio** downloads the editable file; **Export PNG** downloads an image.

Every run is also saved on the server in `backend/outputs/` (see [Outputs and logs](#outputs-and-logs)).

## Deploying with Docker

Needs Docker Desktop (or Docker Engine with the compose plugin) and an API key for an AI model.

```bash
cp backend/.env.example backend/.env     # then fill in your API key and model (see Configuration)
docker compose up -d --build
```

Open **http://localhost:3000**.

Three containers run:

| Container | What it is | Port |
|---|---|---|
| `web` | The frontend, built into static files and served by nginx. nginx also forwards `/api` to the backend | 3000 |
| `backend` | The Python API that talks to the AI, checks the diagram and lays it out | internal only |
| `drawio` | Self-hosted draw.io editor, shown inside the page | 8080 |

**On a server:** users' browsers load the editor directly from the `drawio` container, so tell the build where
that is, and open ports 3000 and 8080 in the firewall:

```bash
DRAWIO_URL=http://<server-address>:8080 docker compose up -d --build
```

`WEB_PORT=80` serves the app on port 80 instead of 3000. Put HTTPS in front (for example a reverse proxy) before real use.

| Task | Command |
|---|---|
| Update after `git pull` | `docker compose up -d --build` |
| See backend logs | `docker compose logs -f backend` |
| Stop | `docker compose down` |

## Configuration

All settings live in `backend/.env` (copy `backend/.env.example`; never commit `.env`).

| Setting | Meaning |
|---|---|
| `PROVIDERS` | Which AI services to try, in order, falling back to the next on failure: `gemini`, `github_models`, `copilot_sdk` |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Google Gemini key (https://aistudio.google.com/apikey) and model id. PDFs and images need Gemini |
| `GEMINI_THOUGHTS` | `true` saves Gemini's summary of its reasoning next to each run |
| `GITHUB_TOKEN`, `GITHUB_MODEL` | GitHub Models token (fine-grained, "Models: read") and model id. Text only |
| `SAVE_OUTPUTS`, `OUTPUT_DIR` | Turn run saving off (`false`) or move it |
| `LOG_LEVEL` | `INFO` by default |

List the model ids your key can use with `python -m scripts.try_it --list` (from `backend/`).
After changing `.env`, restart the backend (`docker compose up -d backend`, or restart uvicorn).

## Developing locally

Runs the frontend and backend with live reload instead of building images.

```bash
docker compose up -d drawio                  # only the editor

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                         # fill in your key
uvicorn app.main:app --reload --port 8000

# in a second terminal, from the repo root
cp .env.example .env
npm install
npm run dev                                  # http://localhost:5173
```

Vite (the frontend build tool) forwards `/api` to `localhost:8000`.

Tests (no API key needed, they use a fake AI): `cd backend && python -m pytest`.

## How it works

```
document ──▶ AI model ──▶ diagram JSON ──▶ check ──▶ layout ──▶ draw.io XML ──▶ editor
                              ▲              │ problems found: ask again (up to 2 times)
                              └──────────────┘
amend:  editor XML ──▶ diagram JSON ──▶ AI applies the change ──▶ check ──▶ layout ──▶ editor
```

The AI only produces the content (lanes, steps, connections, confidence). Positions, sizes and arrow routes are
computed by `convert.py`: steps are placed in columns by their order in the flow, arrows are routed through the gaps
between boxes so they never cross a box, and arrows sharing a gap get their own track so they never overlap.

## Important files

**Backend** (`backend/app/`)

| File | Job |
|---|---|
| `main.py` | The API: `POST /api/generate` (text and/or file) and `POST /api/amend` (current diagram + instruction) |
| `prompts.py` | The instructions sent to the AI: the JSON format, level of detail, confidence scale, amend rules. **Edit this to change what the AI produces** |
| `schema.py` | The diagram JSON format, and the checks every diagram must pass (one start, labelled decision exits, nothing unreachable...) |
| `pipeline.py` | Ask the AI, check the reply, and ask again with the problems listed |
| `providers.py` | Talks to Gemini / GitHub Models / Copilot SDK, with fallback |
| `extract.py` | Turns an upload into something the AI can read (Word files become text plus pictures) |
| `convert.py` | Diagram JSON to draw.io XML: layout, arrow routing, lane colours, shape sizes |
| `read_drawio.py` | draw.io XML back to diagram JSON, so edited diagrams can be amended |
| `history.py`, `log.py` | Save every run to `outputs/`, write `logs/backend.log` |
| `tests/test_backend.py` | Tests with a fake AI |
| `scripts/try_it.py` | Check your key and list model ids without the web app |

**Frontend** (`src/`)

| File | Job |
|---|---|
| `App.tsx` | Screen flow: input, progress, editor |
| `pages.tsx` | The pages, the amend panel and the Needs review list |
| `DrawioEditor.tsx` | Embeds draw.io in an iframe and talks to it |
| `api.ts` | Calls `/api/generate` and `/api/amend` |
| `review.ts` | Finds low-confidence items in the diagram and marks them reviewed |
| `styles.css` | All styling |

**Deployment:** `docker-compose.yml`, `Dockerfile` (frontend + nginx), `nginx.conf`, `backend/Dockerfile`.

## Outputs and logs

Every run, including failed ones and amendments, is saved to `backend/outputs/<input name>-<hash>/`:
`<time>_<model>.drawio` (the diagram), `.json` (run details, problems found, final diagram),
`_attemptN.json` (the AI's raw reply) and `_attemptN_thoughts.md` (Gemini's reasoning summary).
Logs are in `backend/logs/backend.log` (sizes only, never document text). Both folders are git-ignored.

## Troubleshooting

| Problem | Fix |
|---|---|
| "The editor did not start" | The `drawio` container is not running or not reachable at `DRAWIO_URL`: `docker compose up -d drawio` |
| `http proxy error ... ECONNRESET` (local dev) | The backend is not running, or something else uses port 8000 |
| "rate limit reached" / "high demand" | The AI service's free tier is busy or used up. Wait and retry, or switch model in `backend/.env` |
| The model in `outputs/` file names is not the one in `.env` | Restart the backend; in local dev also check the variable is not set in your terminal (`unset GEMINI_MODEL`) |
| Document refused as too long | Text over 15,000 characters is not supported yet (chunking is not built) |

## Known limits

- Documents over 15,000 characters of text are refused.
- PDFs and images need `PROVIDERS=gemini`; the other providers take text only.
- Confidence scores are the AI's own estimate: a guide for what to review, not a measurement.
- Documents are sent to the hosted AI service. Only use documents you are allowed to share with it.
