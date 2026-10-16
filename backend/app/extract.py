"""Turn an uploaded file into attachments the model reads directly (PDF, image, text).
Word files are the exception: Gemini cannot open .docx, so we send its text plus any pictures inside it."""
import io
import logging
from dataclasses import dataclass

from fastapi import UploadFile

log = logging.getLogger("app.extract")

# Gemini allows about 20 MB per request, and files grow by a third when base64 encoded.
# All files of one request share this limit, since they go to the AI together.
MAX_FILE_BYTES = 14 * 1024 * 1024
MAX_FILES = 10

MIME_BY_EXT = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".md": "text/plain",
}
# Picture types Gemini accepts. Others found inside Word files (e.g. EMF from Visio) are skipped.
IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}


class ExtractError(Exception):
    pass


@dataclass
class Attachment:
    name: str
    mime: str
    data: bytes

    @property
    def is_text(self) -> bool:
        return self.mime == "text/plain"


async def read_upload(file: UploadFile) -> list[Attachment]:
    name = file.filename or "upload"
    data = await file.read()
    ext = "." + name.lower().rsplit(".", 1)[-1] if "." in name else ""
    log.info("upload %r: %d bytes", name, len(data))
    if len(data) > MAX_FILE_BYTES:
        raise ExtractError(f"This file is too large ({len(data) // (1024 * 1024)} MB). The limit is {MAX_FILE_BYTES // (1024 * 1024)} MB.")
    if ext in MIME_BY_EXT:
        return [Attachment(name, MIME_BY_EXT[ext], data)]
    if ext == ".docx":
        return _docx(name, data)
    raise ExtractError("Unsupported file type. Use .pdf, .docx, .txt, .md, .png, .jpg or .webp.")


def _docx(name: str, data: bytes) -> list[Attachment]:
    from docx import Document
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            parts.append(" | ".join(c.text.strip() for c in row.cells))
    text = "\n".join(parts).strip()
    out = [Attachment(name, "text/plain", text.encode("utf-8"))] if text else []
    for i, rel in enumerate(doc.part.rels.values()):
        if "image" not in rel.reltype or rel.is_external:
            continue
        img = rel.target_part
        if img.content_type in IMAGE_MIMES:
            out.append(Attachment(f"{name} picture {i + 1}", img.content_type, img.blob))
        else:
            log.warning("skipped picture in %r: %s is not supported", name, img.content_type)
    log.info("docx %r: %d chars of text, %d pictures", name, len(text), len(out) - bool(text))
    if not out:
        raise ExtractError("This Word file has no text or pictures that can be read.")
    return out
