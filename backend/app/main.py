import logging
import time

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(override=True)

from .log import setup_logging  # noqa: E402

setup_logging()
log = logging.getLogger("app.main")

from .convert import to_drawio_xml  # noqa: E402
from .history import save_run  # noqa: E402
from .extract import ExtractError, read_upload  # noqa: E402
from .pipeline import PipelineError, generate_diagram  # noqa: E402
from .providers import ProviderChain, ProviderError, build_providers_from_env  # noqa: E402

MAX_CHARS = 15000  # long-document chunking is not built yet

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
