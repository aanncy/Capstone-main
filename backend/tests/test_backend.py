import asyncio
import json
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

from app.convert import to_drawio_xml
from app.main import app, get_provider
from app.pipeline import PipelineError, generate_diagram, parse_json
from app.providers import ProviderChain, ProviderError

GOOD = {
    "title": "Payment request",
    "lanes": [{"id": "maker", "name": "Maker"}, {"id": "approver", "name": "Approver"}],
    "nodes": [
        {"id": "n1", "type": "start", "label": "Request received", "lane": "maker", "source_ref": "P1", "confidence": 0.95},
        {"id": "n2", "type": "task", "label": "Prepare documents", "lane": "maker", "source_ref": "P1", "confidence": 0.9},
        {"id": "n3", "type": "decision", "label": "Within limit?", "lane": "approver", "source_ref": "P1", "confidence": 0.6},
        {"id": "n4", "type": "end", "label": "Payment released", "lane": "approver", "source_ref": "P1", "confidence": 0.9},
    ],
    "edges": [
        {"from": "n1", "to": "n2", "label": ""},
        {"from": "n2", "to": "n3", "label": ""},
        {"from": "n3", "to": "n4", "label": "Yes"},
        {"from": "n3", "to": "n2", "label": "No"},
    ],
}


class Fake:
    name = "fake"

    def __init__(self, *replies):
        self.replies, self.calls, self.attachments = list(replies), 0, []

    async def complete(self, system, user, attachments=()):
        self.calls += 1
        self.attachments.append(list(attachments))
        return self.replies.pop(0)


def test_parse_json_handles_fences_and_chatter():
    assert parse_json("Sure!\n```json\n" + json.dumps(GOOD) + "\n```")["title"] == "Payment request"


def test_valid_reply_needs_one_call():
    p = Fake(json.dumps(GOOD))
    d = asyncio.run(generate_diagram("text", p))
    assert p.calls == 1 and len(d.nodes) == 4


def test_bad_reply_is_fixed_automatically():
    bad = json.loads(json.dumps(GOOD))
    bad["edges"] = [e for e in bad["edges"] if e["label"] != "No"]  # decision with one exit
    p = Fake(json.dumps(bad), json.dumps(GOOD))
    d = asyncio.run(generate_diagram("text", p))
    assert p.calls == 2 and d.title == "Payment request"


def test_gives_up_after_retries():
    p = Fake("not json", "still not json", "nope")
    try:
        asyncio.run(generate_diagram("text", p))
        assert False, "should have raised"
    except PipelineError as e:
        assert "3 tries" in str(e) and p.calls == 3


def test_xml_is_well_formed_and_keeps_custom_fields():
    from app.schema import Diagram
    root = ET.fromstring(to_drawio_xml(Diagram.model_validate(GOOD)))
    objs = {o.get("id"): o for o in root.iter("object")}
    assert set(objs) == {"n1", "n2", "n3", "n4"} and objs["n3"].get("confidence") == "0.6"
    ids = [e.get("id") for e in root.iter() if e.get("id")]
    assert len(ids) == len(set(ids))


def test_chain_falls_back_to_next_provider():
    class Down:
        name = "down"

        async def complete(self, s, u, a=()):
            raise ProviderError("rate limit")

    assert asyncio.run(ProviderChain([Down(), Fake("ok")]).complete("s", "u")) == "ok"


def test_endpoint_returns_xml_and_clear_errors():
    app.dependency_overrides[get_provider] = lambda: Fake(json.dumps(GOOD))
    c = TestClient(app)
    r = c.post("/api/generate", data={"text": "A process"})
    assert r.status_code == 200 and r.json()["xml"].startswith("<mxfile")
    r = c.post("/api/generate", data={"text": "  "})
    assert r.status_code == 400 and "Add a description" in r.json()["detail"]
    r = c.post("/api/generate", files={"file": ("notes.xls", b"x")})
    assert r.status_code == 400 and "Unsupported file type" in r.json()["detail"]
    app.dependency_overrides.clear()


def test_files_are_sent_to_the_model_on_every_try():
    bad = json.loads(json.dumps(GOOD))
    bad["edges"] = bad["edges"][:-1]
    fake = Fake(json.dumps(bad), json.dumps(GOOD))
    app.dependency_overrides[get_provider] = lambda: fake
    r = TestClient(app).post("/api/generate", files={"file": ("flow.pdf", b"%PDF-1.4 scan")})
    app.dependency_overrides.clear()
    assert r.status_code == 200 and fake.calls == 2
    assert all([(a.name, a.mime, a.data) for a in call] == [("flow.pdf", "application/pdf", b"%PDF-1.4 scan")]
               for call in fake.attachments)


def test_word_file_sends_text_and_pictures():
    import base64
    import io
    from docx import Document
    from app.extract import _docx
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
    doc = Document()
    doc.add_paragraph("Maker prepares the request.")
    doc.add_picture(io.BytesIO(png))
    buf = io.BytesIO()
    doc.save(buf)
    out = _docx("p.docx", buf.getvalue())
    assert [a.mime for a in out] == ["text/plain", "image/png"] and b"Maker" in out[0].data and out[1].data == png


def test_text_only_providers_take_text_files_but_refuse_pdfs():
    from app.extract import Attachment
    from app.providers import text_only
    assert "hello" in text_only("u", [Attachment("a.txt", "text/plain", b"hello")], "X")
    try:
        text_only("u", [Attachment("a.pdf", "application/pdf", b"%PDF")], "X")
        assert False, "should have raised"
    except ProviderError as e:
        assert "PROVIDERS=gemini" in str(e)


def test_runs_are_saved_side_by_side_per_input(tmp_path, monkeypatch):
    from app.extract import Attachment
    from app.history import save_run
    from app.schema import Diagram
    monkeypatch.setenv("SAVE_OUTPUTS", "true")
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    d = Diagram.model_validate(GOOD)
    pdf = [Attachment("flow.pdf", "application/pdf", b"%PDF")]
    tries = [{"attempt": 1, "reply": "oops", "problems": ["not JSON"], "thoughts": "Found two roles."},
             {"attempt": 2, "reply": "```json\n" + json.dumps(GOOD) + "\n```", "problems": []}]
    a = save_run("", "flow.pdf", pdf, {"model": "gemini/flash"}, tries, d, to_drawio_xml(d))
    b = save_run("", "flow.pdf", pdf, {"model": "github_models/openai/gpt-4.1"}, tries[:1], error="gave up")
    assert a.parent == b.parent and a.parent.name.startswith("flow-") and b.name.endswith("gpt-4.1_FAILED.json")
    stem = a.with_suffix("")
    assert stem.with_suffix(".drawio").exists() and not b.with_suffix(".drawio").exists()
    assert (a.parent / f"{stem.name}_attempt1.txt").read_text() == "oops"
    assert (a.parent / f"{stem.name}_attempt1_thoughts.md").read_text() == "Found two roles."
    assert not (a.parent / f"{stem.name}_attempt2_thoughts.md").exists()
    assert json.loads((a.parent / f"{stem.name}_attempt2.json").read_text())["title"] == "Payment request"
    meta = json.loads(a.read_text())
    assert meta["run"]["attempts"][0]["problems"] == ["not JSON"] and meta["diagram"]["title"] == "Payment request"


def test_gemini_thoughts_are_kept_out_of_the_answer(monkeypatch):
    import httpx
    from app.providers import GeminiProvider
    sent = {}

    async def post(self, url, headers=None, json=None):
        sent.update(json)
        parts = [{"text": "Lanes: Maker, Approver.", "thought": True}, {"text": '{"title": "x"}'}]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})
    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    chain = ProviderChain([GeminiProvider("key", "gemini-test", thoughts=True)])
    assert asyncio.run(chain.complete("s", "u")) == '{"title": "x"}'
    assert chain.thoughts == "Lanes: Maker, Approver."
    assert sent["generationConfig"]["thinkingConfig"] == {"includeThoughts": True}
