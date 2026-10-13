import logging
import os
import time

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv(override=True)

from .log import setup_logging  # noqa: E402

setup_logging()
log = logging.getLogger("app.main")

from .convert import to_drawio_xml  # noqa: E402
from .history import save_run  # noqa: E402
from .extract import MAX_FILE_BYTES, MAX_FILES, Attachment, ExtractError, read_upload  # noqa: E402
from .pipeline import PipelineError, amend_diagram, generate_diagram  # noqa: E402
from .read_drawio import DrawioError, from_drawio_xml  # noqa: E402
from .providers import ProviderChain, ProviderError, build_providers_from_env  # noqa: E402

MAX_INSTRUCTION = 2000

app = FastAPI(title="Process Flow backend")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


def max_chars() -> int:
    """Most characters of text (typed plus text files) one request may carry. Gemini reads long inputs (about
    4 characters per token, 1M-token context); GitHub Models' free tier takes only about 8,000 tokens."""
    if os.getenv("MAX_INPUT_CHARS"):
        return int(os.environ["MAX_INPUT_CHARS"])
    first = os.getenv("PROVIDERS", "github_models").split(",")[0].strip()
    return 300_000 if first == "gemini" else 15_000


def get_provider() -> ProviderChain:
    return build_providers_from_env()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/generate")
async def generate(
    text: str = Form(""),
    files: list[UploadFile] = File([]),  # several sources about one process: SOP, transcript, rough diagram...
    file: UploadFile | None = File(None),  # older single-file form field, still accepted
    provider: ProviderChain = Depends(get_provider),
):
    uploads = [f for f in files + ([file] if file else []) if f.filename]
    names = [f.filename for f in uploads]
    log.info("generate: text=%d chars, files=%r", len(text), names)
    if len(uploads) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Upload at most {MAX_FILES} files at once.")
    attachments = []
    for f in uploads:
        try:
            attachments += await read_upload(f)
        except ExtractError as e:
            log.warning("upload rejected for %r: %s", f.filename, e)
            raise HTTPException(status_code=400, detail=f"{f.filename}: {e}")
    if attachments:
        log.info("sending %s", [(a.name, a.mime, len(a.data)) for a in attachments])
    if not text.strip() and not attachments:
        raise HTTPException(status_code=400, detail="Add a description or a file.")
    size = sum(len(a.data) for a in attachments)
    if size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"The files add up to {size // (1024 * 1024)} MB. Together they "
                                                    f"must stay under {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    chars, limit = len(text) + sum(len(a.data) for a in attachments if a.is_text), max_chars()
    if chars > limit:
        log.warning("input too long: %d chars", chars)
        raise HTTPException(status_code=413, detail=f"The text is too long ({chars:,} characters). The limit is {limit:,}.")
    start, attempts = time.monotonic(), []
    # runs are saved in a folder named after the input: the file, or the first file and how many others
    label = None if not names else names[0] if len(names) == 1 else f"{names[0].rsplit('.', 1)[0]} +{len(names) - 1} more"

    def save(**kw):
        save_run(text, label, attachments, attempts=attempts, run={
            "model": getattr(provider, "used", None), "model_calls": getattr(provider, "calls", None),
            "seconds": round(time.monotonic() - start, 1)}, **kw)

    try:
        diagram = await generate_diagram(text, provider, attachments, trace=attempts)
    except ProviderError as e:
        log.error("provider failed: %s", e)
        save(error=str(e))
        raise HTTPException(status_code=502, detail=f"Could not reach the AI service. {e}")
    except PipelineError as e:
        log.error("pipeline failed: %s", e)
        save(error=str(e))
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        log.exception("unexpected error")
        raise
    log.info("generate ok: %d nodes, %d edges", len(diagram.nodes), len(diagram.edges))
    xml = to_drawio_xml(diagram)
    save(diagram=diagram, xml=xml)
    return {"xml": xml, "diagram": diagram.model_dump(by_alias=True)}


class AmendRequest(BaseModel):
    xml: str  # the diagram as it is now in the editor, including the user's own edits
    instruction: str


@app.post("/api/amend")
async def amend(req: AmendRequest, provider: ProviderChain = Depends(get_provider)):
    instruction = req.instruction.strip()
    log.info("amend: instruction=%d chars, xml=%d chars", len(instruction), len(req.xml))
    if not instruction:
        raise HTTPException(status_code=400, detail="Describe the change you want.")
    if len(instruction) > MAX_INSTRUCTION:
        raise HTTPException(status_code=413, detail=f"Keep the change under {MAX_INSTRUCTION} characters.")
    try:
        current = from_drawio_xml(req.xml)
    except (DrawioError, ValueError) as e:
        log.warning("amend: could not read the diagram: %s", e)
        raise HTTPException(status_code=400, detail=f"Could not read the current diagram. {e}")
    log.info("amend: current diagram has %d nodes, %d edges", len(current.nodes), len(current.edges))
    start, attempts = time.monotonic(), []
    # saved like a generate run; the diagram before the change counts as the input file
    before = [Attachment("diagram_before.json", "application/json",
                         current.model_dump_json(by_alias=True, indent=1).encode("utf-8"))]

    def save(**kw):
        save_run(instruction, f"amend-{current.title}", before, attempts=attempts, run={
            "model": getattr(provider, "used", None), "model_calls": getattr(provider, "calls", None),
            "seconds": round(time.monotonic() - start, 1)}, **kw)

    try:
        diagram = await amend_diagram(current, instruction, provider, trace=attempts)
    except ProviderError as e:
        log.error("provider failed: %s", e)
        save(error=str(e))
        raise HTTPException(status_code=502, detail=f"Could not reach the AI service. {e}")
    except PipelineError as e:
        log.error("pipeline failed: %s", e)
        save(error=str(e))
        raise HTTPException(status_code=502, detail=str(e))
    except Exception:
        log.exception("unexpected error")
        raise
    log.info("amend ok: %d nodes, %d edges", len(diagram.nodes), len(diagram.edges))
    xml = to_drawio_xml(diagram)
    save(diagram=diagram, xml=xml)
    return {"xml": xml, "diagram": diagram.model_dump(by_alias=True)}
