import logging
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
from .extract import Attachment, ExtractError, read_upload  # noqa: E402
from .pipeline import PipelineError, amend_diagram, generate_diagram  # noqa: E402
from .read_drawio import DrawioError, from_drawio_xml  # noqa: E402
from .providers import ProviderChain, ProviderError, build_providers_from_env  # noqa: E402

MAX_CHARS = 15000  # long-document chunking is not built yet
MAX_INSTRUCTION = 2000

app = FastAPI(title="Process Flow backend")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"], allow_methods=["*"], allow_headers=["*"])


def get_provider() -> ProviderChain:
    return build_providers_from_env()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/generate")
async def generate(
    text: str = Form(""),
    file: UploadFile | None = File(None),
    provider: ProviderChain = Depends(get_provider),
):
    log.info("generate: text=%d chars, file=%r", len(text), file.filename if file else None)
    attachments = []
    if file is not None and file.filename:
        try:
            attachments = await read_upload(file)
        except ExtractError as e:
            log.warning("upload rejected for %r: %s", file.filename, e)
            raise HTTPException(status_code=400, detail=str(e))
        log.info("sending %s", [(a.name, a.mime, len(a.data)) for a in attachments])
    if not text.strip() and not attachments:
        raise HTTPException(status_code=400, detail="Add a description or a file.")
    chars = len(text) + sum(len(a.data) for a in attachments if a.is_text)
    if chars > MAX_CHARS:
        log.warning("input too long: %d chars", chars)
        raise HTTPException(status_code=413, detail=f"This document is too long ({chars} characters). The limit is {MAX_CHARS} until chunking is built.")
    start, attempts = time.monotonic(), []

    def save(**kw):
        save_run(text, file.filename if file else None, attachments, attempts=attempts, run={
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
