"""Save every run so outputs on the same input can be compared later.
Layout: outputs/<input name>-<input hash>/<time>_<model>[_FAILED].* with
  .drawio            the final diagram as draw.io XML (successful runs only)
  .json              run details, each attempt's problems, and the final diagram
  _attempt<N>.json   the model's raw reply for that attempt (.txt if it was not valid JSON)
  _attempt<N>_thoughts.md   the model's summary of its reasoning for that attempt (Gemini only, if it sent one)"""
import hashlib
import json
import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

from .pipeline import parse_json

log = logging.getLogger("app.history")

DEFAULT_DIR = Path(__file__).resolve().parent.parent / "outputs"


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-")[:60] or "input"


def save_run(text: str, file_name: str | None, attachments, run: dict, attempts=(), diagram=None, xml=None,
             error: str | None = None) -> Path | None:
    """Write the files for one run and return the .json path. Never fails the request: problems are only logged."""
    if os.getenv("SAVE_OUTPUTS", "true").lower() == "false":
        return None
    try:
        h = hashlib.sha256(text.encode("utf-8"))
        for a in attachments:
            h.update(a.data)
        folder = Path(os.getenv("OUTPUT_DIR") or DEFAULT_DIR) / f"{_slug(Path(file_name).stem if file_name else 'text')}-{h.hexdigest()[:8]}"
        folder.mkdir(parents=True, exist_ok=True)
        stem = f"{datetime.now():%Y-%m-%d_%H%M%S}_{_slug(run.get('model') or 'unknown')}" + ("_FAILED" if error else "")
        if xml is not None:
            tree = ET.fromstring(xml)
            ET.indent(tree)  # one element per line so the XML is readable; draw.io opens it the same
            (folder / f"{stem}.drawio").write_text(ET.tostring(tree, encoding="unicode"), encoding="utf-8")
        for a in attempts:
            try:
                (folder / f"{stem}_attempt{a['attempt']}.json").write_text(
                    json.dumps(parse_json(a["reply"]), indent=2, ensure_ascii=False), encoding="utf-8")
            except json.JSONDecodeError:
                (folder / f"{stem}_attempt{a['attempt']}.txt").write_text(a["reply"], encoding="utf-8")
            if a.get("thoughts"):
                (folder / f"{stem}_attempt{a['attempt']}_thoughts.md").write_text(a["thoughts"], encoding="utf-8")
        meta = {"saved_at": datetime.now().isoformat(timespec="seconds"), "file": file_name, "typed_text": text,
                "attachments": [{"name": a.name, "mime": a.mime, "bytes": len(a.data)} for a in attachments],
                **run, "error": error,
                "attempts": [{"attempt": a["attempt"], "problems": a["problems"]} for a in attempts]}
        out = folder / f"{stem}.json"
        out.write_text(json.dumps({"run": meta, "diagram": diagram.model_dump(by_alias=True) if diagram else None},
                                  indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("saved %s", out)
        return out
    except (OSError, ET.ParseError) as e:
        log.error("could not save output: %s", e)
        return None
