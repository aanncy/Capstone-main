# Process Flow Tool: backend

Python (FastAPI). Takes text or a file, asks an AI model for a diagram as JSON, checks it, fixes it automatically if needed,
and returns draw.io XML to the frontend.

## Set up (PyCharm)

1. Open the `backend` folder in PyCharm (or open your whole repo and use `backend/` inside it).
2. Settings > Project > Python Interpreter > Add Interpreter > Virtualenv (Python 3.10 or newer).
3. In the PyCharm Terminal, from the `backend` folder:
   ```
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and paste your GitHub token after `GITHUB_TOKEN=`.
   Create the token at https://github.com/settings/personal-access-tokens (fine-grained, account permission "Models": read).
   Never commit `.env`.

## Check it works (in this order)

```
python -m pytest                    # no token needed: tests the logic with a fake AI
python -m scripts.try_it --list     # needs the token: shows model ids; copy one into GITHUB_MODEL in .env
python -m scripts.try_it            # real AI call; saves out.drawio and prints the JSON
```

## Run the server

```
uvicorn app.main:app --reload --port 8000
```

In PyCharm you can also create a Run Configuration of type "Python", choose "Module name" = `uvicorn`, parameters
`app.main:app --reload --port 8000`, working directory = `backend`.

Then in the frontend project set `VITE_USE_MOCK=false` in `.env`, restart `npm run dev`, and click Create diagram.

## How it fits together

| File | Job |
|---|---|
| `app/main.py` | The web API: `POST /api/generate` |
| `app/extract.py` | Turns the upload into attachments the AI reads directly (.pdf, .png, .jpg, .webp, .txt, .md). Gemini cannot open .docx, so Word files are sent as their text plus their pictures |
| `app/history.py` | Saves every run (failed ones too, marked `_FAILED`) to `outputs/<input>-<hash>/`: the final `.drawio` XML, a `.json` with run details and the final diagram, and `_attemptN.json` with the model's raw reply for each try. Turn off with `SAVE_OUTPUTS=false`; move with `OUTPUT_DIR` |
| `app/log.py` | Writes logs to `logs/backend.log` (sizes only, never document text) |
| `app/prompts.py` | The instructions sent to the AI, including the JSON format |
| `app/providers.py` | Talks to the AI. GitHub Models works now; Copilot SDK is an untested option. Falls back down the list in `PROVIDERS` |
| `app/schema.py` | The JSON format plus the checks (every decision has labelled exits, nothing unreachable...) |
| `app/pipeline.py` | Ask, check, and automatically ask again with the problems listed (up to 2 fixes) |
| `app/convert.py` | JSON to draw.io XML. Placeholder layout: replace with ELK layout later |
| `tests/test_backend.py` | Tests using a fake AI |

## Known limits

- Layout is a simple left-to-right placeholder. Long diagrams get wide.
- Documents over 15,000 characters are refused (chunking not built).
- PDFs and images (including scans and flow chart pictures) need `PROVIDERS=gemini`. GitHub Models and Copilot SDK only take typed text and .txt/.md/.docx text.
- Uploads are limited to 14 MB (Gemini's inline request limit). Pictures in Word files that Gemini cannot read, such as EMF from Visio, are skipped and logged.
- Free GitHub Models usage is rate limited. One diagram takes 1 to 3 calls.
- Documents are sent to GitHub's hosted models. Use only documents you are allowed to share.
