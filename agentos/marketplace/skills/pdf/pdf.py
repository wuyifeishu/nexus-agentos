"""
pdf — PDF operations using PyPDF2.

Actions: read, pages, metadata, extract_text
"""

from typing import Any


def run(action: str = "read", file_path: str = "", page: int = 0, **kwargs: Any) -> str:
    try:
        from PyPDF2 import PdfReader
    except ImportError:
        return "[pdf] PyPDF2 not installed. Run: pip install PyPDF2"

    try:
        reader = PdfReader(file_path)
    except FileNotFoundError:
        return f"[pdf] File not found: {file_path}"
    except Exception as e:
        return f"[pdf] Error: {e}"

    if action == "metadata":
        meta = reader.metadata
        if meta:
            return f"Title: {meta.get('/Title','N/A')}\nAuthor: {meta.get('/Author','N/A')}\nPages: {len(reader.pages)}"
        return f"[pdf] No metadata. Pages: {len(reader.pages)}"

    if action == "pages":
        return f"Total pages: {len(reader.pages)}"

    if action == "read":
        text = ""
        for p in reader.pages[: min(len(reader.pages), 5)]:
            text += p.extract_text() or ""
        return text[:3000] or "[pdf] No extractable text on first 5 pages."

    if action == "extract_text":
        p = reader.pages[page]
        return p.extract_text() or f"[pdf] No text on page {page + 1}."

    return f"[pdf] Unknown action: {action}"


__all__ = ["run"]
