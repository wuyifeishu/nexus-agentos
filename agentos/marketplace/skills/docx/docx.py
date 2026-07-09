"""
docx — Word document (.docx) operations using python-docx.

Actions: read, paragraphs, tables, metadata, stats
"""

from typing import Any


def run(action: str = "read", file_path: str = "", **kwargs: Any) -> str:
    try:
        from docx import Document
    except ImportError:
        return "[docx] python-docx not installed. Run: pip install python-docx"

    try:
        doc = Document(file_path)
    except FileNotFoundError:
        return f"[docx] File not found: {file_path}"
    except Exception as e:
        return f"[docx] Error: {e}"

    if action == "metadata":
        props = doc.core_properties
        return (
            f"Title: {props.title or 'N/A'}\n"
            f"Author: {props.author or 'N/A'}\n"
            f"Modified: {props.modified or 'N/A'}\n"
            f"Paragraphs: {len(doc.paragraphs)}, Tables: {len(doc.tables)}"
        )

    if action == "paragraphs":
        lines = [p.text for p in doc.paragraphs if p.text.strip()]
        return f"Paragraphs ({len(lines)}):\n" + "\n".join(lines[:30])

    if action == "tables":
        result = []
        for i, table in enumerate(doc.tables):
            headers = [cell.text for cell in table.rows[0].cells]
            result.append(f"Table {i+1}: {len(table.rows)} rows, Headers: {headers}")
        return "\n".join(result) if result else "[docx] No tables found."

    if action == "stats":
        para_count = len(doc.paragraphs)
        table_count = len(doc.tables)
        word_count = sum(len(p.text.split()) for p in doc.paragraphs)
        return f"Paragraphs: {para_count}, Tables: {table_count}, Words: ~{word_count}"

    # Default: read
    text = "\n".join(p.text for p in doc.paragraphs[:50])
    return text[:3000]


__all__ = ["run"]
