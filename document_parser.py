from __future__ import annotations

import csv
import io
import re
from pathlib import Path


SUPPORTED = {".pdf", ".docx", ".txt", ".md", ".rtf", ".pptx", ".xlsx", ".csv",
             ".png", ".jpg", ".jpeg", ".webp"}


def extract_text(filename: str, data: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported format: {ext or 'unknown'}. Supported: PDF, DOCX, TXT, MD, RTF, PPTX, XLSX, CSV, PNG, JPG, JPEG and WEBP.")
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        parts = [(page.extract_text() or "") for page in reader.pages[:100]]
        text = "\\n\\n".join(parts)
    elif ext == ".docx":
        from docx import Document
        doc = Document(io.BytesIO(data))
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        text = "\\n".join(parts)
    elif ext in {".txt", ".md"}:
        text = data.decode("utf-8-sig", errors="replace")
    elif ext == ".rtf":
        raw = data.decode("utf-8", errors="replace")
        text = re.sub(r"\\\\'[0-9a-fA-F]{2}", " ", raw)
        text = re.sub(r"\\\\[a-zA-Z]+-?\\d* ?", " ", text)
        text = re.sub(r"[{}]", " ", text)
    elif ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(io.BytesIO(data))
        parts = []
        for slide in prs.slides[:100]:
            for shape in slide.shapes:
                if hasattr(shape, "text") and shape.text:
                    parts.append(shape.text)
        text = "\\n".join(parts)
    elif ext == ".xlsx":
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        parts = []
        for ws in wb.worksheets[:20]:
            parts.append(f"[Sheet: {ws.title}]")
            for row in ws.iter_rows(max_row=500, max_col=40, values_only=True):
                vals = [str(v) for v in row if v is not None]
                if vals:
                    parts.append(" | ".join(vals))
        text = "\\n".join(parts)
        wb.close()
    elif ext == ".csv":
        decoded = data.decode("utf-8-sig", errors="replace")
        rows = list(csv.reader(io.StringIO(decoded)))[:1000]
        text = "\\n".join(" | ".join(row[:40]) for row in rows)
    else:
        from PIL import Image
        import pytesseract
        image = Image.open(io.BytesIO(data)).convert("RGB")
        image.thumbnail((3000, 3000))
        text = pytesseract.image_to_string(image)

    text = text.strip()
    if not text:
        raise ValueError("No readable text was found in this file. Scanned PDFs may need OCR before they can be used.")
    return text[:120_000]
