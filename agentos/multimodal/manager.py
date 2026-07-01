"""
AgentOS v0.40 Multimodal — 多模态输入支持。
支持：图片理解、语音转文字、PDF/文档解析。
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


logger = logging.getLogger(__name__)


class Modality(str, Enum):

    """模态类型枚举。"""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"


@dataclass
class MultimodalBlock:
    """多模态输入块 — 遵循OpenAI/Anthropic content block格式。"""
    type: str  # text | image_url | audio | image
    text: str = ""
    source: dict = field(default_factory=dict)
    mime_type: str = ""

    @classmethod
    def text_block(cls, text: str) -> "MultimodalBlock":
        return cls(type="text", text=text)

    @classmethod
    def image_url(cls, url: str, detail: str = "auto") -> "MultimodalBlock":
        return cls(type="image_url", source={"type": "image_url", "image_url": {"url": url, "detail": detail}})

    @classmethod
    def image_base64(cls, data: bytes, mime: str = "image/jpeg") -> "MultimodalBlock":
        b64 = base64.b64encode(data).decode()
        return cls(type="image_url", source={"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})

    @classmethod
    def audio(cls, data: bytes, mime: str = "audio/wav") -> "MultimodalBlock":
        b64 = base64.b64encode(data).decode()
        return cls(type="audio", mime_type=mime, source={"data": b64})

    def to_openai_format(self) -> dict:
        if self.type == "text":
            return {"type": "text", "text": self.text}
        if self.type == "image_url":
            return {"type": "image_url", "image_url": self.source["image_url"]}
        return {"type": self.type, **self.source}


class ImageProcessor:
    """图片处理器 — 压缩、格式转换、OCR预处理。"""

    MAX_SIZE = 2048
    JPEG_QUALITY = 85

    @staticmethod
    def encode_file(path: str) -> tuple[str, str]:
        """返回(base64, mime_type)。"""
        import mimetypes
        mime = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode(), mime

    @staticmethod
    def encode_bytes(data: bytes, mime: str = "image/jpeg") -> str:
        return base64.b64encode(data).decode()

    @staticmethod
    def estimate_tokens(width: int, height: int, detail: str = "auto") -> int:
        """估算图片token消耗（OpenAI定价模型）。"""
        if detail == "low":
            return 85
        # high detail
        short_side = min(width, height)
        scale = min(768 / short_side, 1.0) if short_side > 768 else 1.0
        w = int(width * scale)
        h = int(height * scale)
        tiles = ((w + 511) // 512) * ((h + 511) // 512)
        return 85 + 170 * tiles

    @staticmethod
    def purge_metadata(data: bytes) -> bytes:
        """清除图片EXIF元数据。"""
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(data))
            data_no_exif = list(img.getdata())
            cleaned = Image.new(img.mode, img.size)
            cleaned.putdata(data_no_exif)
            buf = io.BytesIO()
            cleaned.save(buf, format=img.format or "PNG")
            return buf.getvalue()
        except ImportError:
            return data


class AudioProcessor:
    """音频处理器 — 转文字、格式转换。"""

    SUPPORTED_FORMATS = ["wav", "mp3", "ogg", "flac", "m4a"]

    @staticmethod
    def transcribe(path: str, whisper_model: str = "base") -> str:
        """使用whisper转文字。"""
        try:
            import whisper
            model = whisper.load_model(whisper_model)
            result = model.transcribe(path)
            return result["text"]
        except ImportError:
            logger.warning("whisper not installed, returning empty")
            return "[whisper not available]"

    @staticmethod
    def encode_file(path: str) -> tuple[str, str]:
        import mimetypes
        mime = mimetypes.guess_type(path)[0] or "audio/wav"
        with open(path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode(), mime


class DocumentParser:
    """文档解析器 — PDF/Word/Markdown。"""

    @staticmethod
    def parse_pdf(path: str) -> str:
        try:
            import PyPDF2
            text = []
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text.append(page_text)
            return "\n\n".join(text)
        except ImportError:
            logger.warning("PyPDF2 not installed")
            return "[PyPDF2 not available]"

    @staticmethod
    def parse_docx(path: str) -> str:
        try:
            from docx import Document
            doc = Document(path)
            return "\n".join(p.text for p in doc.paragraphs if p.text)
        except ImportError:
            logger.warning("python-docx not installed")
            return "[python-docx not available]"

    @staticmethod
    def parse_auto(path: str) -> tuple[str, str]:
        """自动检测文件类型并解析。返回 (content, format)。"""
        ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
        if ext == "pdf":
            return DocumentParser.parse_pdf(path), "pdf"
        elif ext in ("docx", "doc"):
            return DocumentParser.parse_docx(path), "docx"
        elif ext in ("md", "markdown", "txt"):
            with open(path) as f:
                return f.read(), ext
        else:
            try:
                with open(path) as f:
                    return f.read(), "text"
            except Exception:
                return "", "unknown"


class MultimodalManager:
    """多模态管理器 — 统一入口。"""

    def __init__(self):
        self.image = ImageProcessor()
        self.audio = AudioProcessor()
        self.document = DocumentParser()

    def prepare_input(self, blocks: list[MultimodalBlock]) -> list[dict]:
        """转换为OpenAI兼容格式。"""
        return [b.to_openai_format() for b in blocks]

    def from_files(self, paths: list[str]) -> list[MultimodalBlock]:
        """从文件路径自动推断模态。"""
        blocks = []
        image_exts = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}
        audio_exts = {"wav", "mp3", "ogg", "flac", "m4a"}
        doc_exts = {"pdf", "docx", "doc", "md", "txt"}

        for p in paths:
            ext = p.rsplit(".", 1)[-1].lower() if "." in p else ""
            try:
                if ext in image_exts:
                    b64, mime = ImageProcessor.encode_file(p)
                    blocks.append(MultimodalBlock(type="image_url",
                            source={"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}))
                elif ext in audio_exts:
                    b64, mime = AudioProcessor.encode_file(p)
                    blocks.append(MultimodalBlock(type="audio", mime_type=mime, source={"data": b64}))
                elif ext in doc_exts:
                    text, fmt = DocumentParser.parse_auto(p)
                    blocks.append(MultimodalBlock.text_block(text))
                else:
                    with open(p) as f:
                        blocks.append(MultimodalBlock.text_block(f.read()))
            except Exception as e:
                blocks.append(MultimodalBlock.text_block(f"[Error reading {p}: {e}]"))
        return blocks

    def stats(self) -> dict:
        return {"modalities": ["text", "image", "audio", "video", "document"]}
