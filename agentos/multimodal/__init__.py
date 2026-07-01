"""
AgentOS v1.14.3 — Multimodal Context Manager.

Unified multimodal context layer for AgentOS agents. Handles images,
audio, video, and structured documents as first-class context objects.

Features:
- Multi-format image processing (PNG, JPEG, GIF, WebP, SVG, HEIC)
- Audio transcription & processing (WAV, MP3, FLAC, M4A)
- Video keyframe extraction & captioning
- PDF/DOCX document text extraction with layout awareness
- File type auto-detection (magic bytes)
- Image preprocessing pipeline (resize, compress, format convert)
- Vision LLM adapter for base64 images
- Thumbnail generation
- Metadata extraction (EXIF, duration, dimensions)

Architecture:
    File Input
        ├── MediaDetector (magic bytes identification)
        ├── MediaProcessor (format-specific pipeline)
        │   ├── ImageProcessor (resize/compress/convert/base64)
        │   ├── AudioProcessor (transcription via whisper)
        │   ├── VideoProcessor (keyframe extraction)
        │   └── DocumentProcessor (PDF/DOCX extraction)
        └── MediaContext (unified context object)

Inspired by: GPT-4V multimodal API, Claude Vision, Gemini 1.5 Pro
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import os
import struct
import subprocess
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any, Dict, List, Optional, Tuple, Union,
)


# ── Types ───────────────────────────────────


class MediaType(str, Enum):
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENT = "document"
    UNKNOWN = "unknown"


class ImageFormat(str, Enum):
    PNG = "png"
    JPEG = "jpeg"
    GIF = "gif"
    WEBP = "webp"
    SVG = "svg"
    BMP = "bmp"
    HEIC = "heic"
    TIFF = "tiff"


@dataclass
class MediaMetadata:
    """媒体文件元数据。"""

    file_path: str = ""
    media_type: MediaType = MediaType.UNKNOWN
    mime_type: str = ""
    file_size_bytes: int = 0

    # Image
    width: int = 0
    height: int = 0
    color_mode: str = ""

    # Audio/Video
    duration_s: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    bitrate_kbps: int = 0

    # General
    has_alpha: bool = False
    page_count: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "file_path": self.file_path,
            "media_type": self.media_type.value,
            "mime_type": self.mime_type,
            "file_size_bytes": self.file_size_bytes,
            "width": self.width,
            "height": self.height,
            "duration_s": self.duration_s,
            "page_count": self.page_count,
        }


@dataclass
class MediaContext:
    """统一的多模态上下文对象。

    This is what gets passed to LLM context windows.
    """

    context_id: str = field(default_factory=lambda: f"mctx-{uuid.uuid4().hex[:12]}")
    media_type: MediaType = MediaType.UNKNOWN
    metadata: MediaMetadata = field(default_factory=MediaMetadata)

    # Processed representations
    text_description: str = ""          # 自然语言描述
    base64_data: str = ""              # Base64 编码（用于视觉 LLM）
    extracted_text: str = ""           # OCR/转录文本
    thumbnail_path: str = ""           # 缩略图路径

    # Structured
    entities: List[Dict[str, Any]] = field(default_factory=list)
    captions: List[str] = field(default_factory=list)

    def to_llm_message(self) -> dict:
        """转换为 LLM API 消息格式。"""
        if self.media_type == MediaType.IMAGE and self.base64_data:
            return {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{self.metadata.mime_type};base64,{self.base64_data}",
                            "detail": "auto",
                        },
                    },
                    {
                        "type": "text",
                        "text": self.text_description or "Describe this image.",
                    },
                ],
            }
        return {
            "role": "user",
            "content": self.text_description or self.extracted_text or "",
        }


# ── Media Detector ──────────────────────────


class MediaDetector:
    """通过文件魔数 (magic bytes) 检测媒体类型。

    Usage:
        detector = MediaDetector()
        mt = detector.detect("photo.jpg")  # MediaType.IMAGE
    """

    # Magic bytes signatures
    MAGIC_SIGNATURES = {
        b'\xFF\xD8\xFF': (MediaType.IMAGE, ImageFormat.JPEG),
        b'\x89PNG\r\n\x1A\n': (MediaType.IMAGE, ImageFormat.PNG),
        b'GIF87a': (MediaType.IMAGE, ImageFormat.GIF),
        b'GIF89a': (MediaType.IMAGE, ImageFormat.GIF),
        b'RIFF': (MediaType.IMAGE, ImageFormat.WEBP),      # WEBP is RIFF{size}WEBP
        b'\x42\x4D': (MediaType.IMAGE, ImageFormat.BMP),
        b'<?xml': (MediaType.IMAGE, ImageFormat.SVG),
        b'<svg': (MediaType.IMAGE, ImageFormat.SVG),
        b'II*\x00': (MediaType.IMAGE, ImageFormat.TIFF),
        b'MM\x00*': (MediaType.IMAGE, ImageFormat.TIFF),
        # Audio
        b'RIFF': (MediaType.AUDIO, None),  # WAV is RIFF
        b'ID3': (MediaType.AUDIO, None),    # MP3 with ID3
        b'\xFF\xFB': (MediaType.AUDIO, None),  # MP3
        b'\xFF\xF3': (MediaType.AUDIO, None),  # MP3
        b'fLaC': (MediaType.AUDIO, None),  # FLAC
        b'OggS': (MediaType.AUDIO, None),  # OGG
        # Video
        b'\x00\x00\x00\x18ftyp': (MediaType.VIDEO, None),  # MP4
        b'\x00\x00\x00\x20ftyp': (MediaType.VIDEO, None),
        b'\x1A\x45\xDF\xA3': (MediaType.VIDEO, None),  # WebM/MKV
        # Documents
        b'%PDF': (MediaType.DOCUMENT, None),
        b'PK\x03\x04': (MediaType.DOCUMENT, None),  # DOCX/XLSX/PPTX (ZIP)
    }

    # Audio extensions
    AUDIO_EXTENSIONS = {'.mp3', '.wav', '.flac', '.m4a', '.ogg', '.aac', '.wma', '.opus'}

    # Video extensions
    VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mkv', '.mov', '.wmv', '.webm', '.flv', '.m4v', '.3gp'}

    # Image extensions
    IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg', '.tiff', '.heic', '.ico'}

    # Document extensions
    DOCUMENT_EXTENSIONS = {'.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt', '.txt', '.md', '.html', '.epub'}

    @classmethod
    def detect(cls, file_path: str) -> MediaType:
        """检测文件媒体类型。"""
        ext = Path(file_path).suffix.lower()

        if ext in cls.IMAGE_EXTENSIONS:
            return MediaType.IMAGE
        if ext in cls.AUDIO_EXTENSIONS:
            return MediaType.AUDIO
        if ext in cls.VIDEO_EXTENSIONS:
            return MediaType.VIDEO
        if ext in cls.DOCUMENT_EXTENSIONS:
            return MediaType.DOCUMENT

        # Fallback to magic bytes
        try:
            with open(file_path, 'rb') as f:
                header = f.read(32)
        except Exception:
            return MediaType.UNKNOWN

        for magic, (mtype, _) in cls.MAGIC_SIGNATURES.items():
            if header.startswith(magic):
                # RIFF ambiguity resolution
                if magic == b'RIFF':
                    if b'WEBP' in header:
                        return MediaType.IMAGE
                    if b'WAVE' in header:
                        return MediaType.AUDIO
                return mtype

        # MIME type fallback
        mime, _ = mimetypes.guess_type(file_path)
        if mime:
            if mime.startswith('image/'):
                return MediaType.IMAGE
            if mime.startswith('audio/'):
                return MediaType.AUDIO
            if mime.startswith('video/'):
                return MediaType.VIDEO

        return MediaType.UNKNOWN

    @classmethod
    def batch_detect(cls, file_paths: List[str]) -> Dict[str, MediaType]:
        """批量检测。"""
        return {fp: cls.detect(fp) for fp in file_paths}


# ── Media Processors ────────────────────────


class MediaProcessor(ABC):
    """媒体处理器基类。"""

    @abstractmethod
    def process(self, file_path: str) -> MediaContext:
        ...

    @abstractmethod
    def extract_metadata(self, file_path: str) -> MediaMetadata:
        ...


class ImageProcessor(MediaProcessor):
    """图像处理器。

    支持格式转换、缩放、压缩、Base64 编码。

    Usage:
        processor = ImageProcessor()
        ctx = processor.process("photo.jpg")
        base64_str = ctx.base64_data  # 可直接用于 LLM API
    """

    def __init__(
        self,
        max_size: int = 2048,
        quality: int = 85,
        output_format: str = "JPEG",
    ):
        self._max_size = max_size
        self._quality = quality
        self._output_format = output_format

    def process(self, file_path: str) -> MediaContext:
        ctx = MediaContext(media_type=MediaType.IMAGE)
        ctx.metadata = self.extract_metadata(file_path)
        ctx.base64_data = self._encode_base64(file_path)
        ctx.text_description = self._generate_description(file_path)
        ctx.thumbnail_path = self._generate_thumbnail(file_path)
        return ctx

    def extract_metadata(self, file_path: str) -> MediaMetadata:
        meta = MediaMetadata(
            file_path=file_path,
            media_type=MediaType.IMAGE,
            mime_type=mimetypes.guess_type(file_path)[0] or "application/octet-stream",
            file_size_bytes=os.path.getsize(file_path) if os.path.exists(file_path) else 0,
        )

        # Try to get dimensions using PIL
        try:
            from PIL import Image
            with Image.open(file_path) as img:
                meta.width = img.width
                meta.height = img.height
                meta.color_mode = img.mode
                meta.has_alpha = img.mode in ('RGBA', 'LA', 'PA')

                # EXIF extraction
                exif = img.getexif()
                if exif:
                    for tag_id, value in exif.items():
                        meta.extra[str(tag_id)] = str(value)
        except ImportError:
            pass
        except Exception:
            pass

        return meta

    def _encode_base64(self, file_path: str) -> str:
        """将图片编码为 Base64。"""
        try:
            with open(file_path, 'rb') as f:
                return base64.b64encode(f.read()).decode('utf-8')
        except Exception:
            return ""

    def _generate_description(self, file_path: str) -> str:
        """生成图片自然语言描述（应由视觉 LLM 生成）。"""
        meta = self.extract_metadata(file_path)
        return f"Image: {meta.width}x{meta.height}, format: {Path(file_path).suffix}"

    def _generate_thumbnail(self, file_path: str) -> str:
        """生成缩略图。"""
        try:
            from PIL import Image

            thumb_dir = Path(tempfile.gettempdir()) / "agentos_thumbnails"
            thumb_dir.mkdir(exist_ok=True)

            thumb_name = f"thumb_{uuid.uuid4().hex[:8]}.jpg"
            thumb_path = thumb_dir / thumb_name

            with Image.open(file_path) as img:
                img.thumbnail((self._max_size, self._max_size))
                img.convert("RGB").save(thumb_path, self._output_format, quality=self._quality)

            return str(thumb_path)
        except Exception:
            return ""

    def resize(self, file_path: str, width: int, height: int, output_path: Optional[str] = None) -> str:
        """缩放图片。"""
        try:
            from PIL import Image

            out = output_path or str(
                Path(tempfile.gettempdir()) / f"resized_{uuid.uuid4().hex[:8]}{Path(file_path).suffix}"
            )

            with Image.open(file_path) as img:
                img.resize((width, height), Image.LANCZOS).save(out)

            return out
        except Exception as e:
            raise RuntimeError(f"Image resize failed: {e}")

    def compress(
        self,
        file_path: str,
        quality: int = 70,
        output_path: Optional[str] = None,
    ) -> str:
        """压缩图片。"""
        try:
            from PIL import Image

            out = output_path or str(
                Path(tempfile.gettempdir()) / f"compressed_{uuid.uuid4().hex[:8]}.jpg"
            )

            with Image.open(file_path) as img:
                img.convert("RGB").save(out, "JPEG", quality=quality, optimize=True)

            return out
        except Exception as e:
            raise RuntimeError(f"Image compression failed: {e}")

    def convert_format(self, file_path: str, target_format: str, output_path: Optional[str] = None) -> str:
        """转换图片格式。"""
        try:
            from PIL import Image

            fmt = target_format.upper().replace('.', '')
            ext = f".{target_format.lower().lstrip('.')}"
            out = output_path or str(
                Path(tempfile.gettempdir()) / f"converted_{uuid.uuid4().hex[:8]}{ext}"
            )

            with Image.open(file_path) as img:
                img.save(out, fmt)

            return out
        except Exception as e:
            raise RuntimeError(f"Format conversion failed: {e}")


class AudioProcessor(MediaProcessor):
    """音频处理器。

    支持转录（需 whisper）、格式转换、元数据提取。

    Usage:
        processor = AudioProcessor()
        ctx = processor.process("recording.mp3")
        print(ctx.extracted_text)  # 转录文本
    """

    def __init__(self, transcription_model: str = "base"):
        self._model = transcription_model

    def process(self, file_path: str) -> MediaContext:
        ctx = MediaContext(media_type=MediaType.AUDIO)
        ctx.metadata = self.extract_metadata(file_path)
        ctx.extracted_text = self._transcribe(file_path)
        return ctx

    def extract_metadata(self, file_path: str) -> MediaMetadata:
        meta = MediaMetadata(
            file_path=file_path,
            media_type=MediaType.AUDIO,
            mime_type=mimetypes.guess_type(file_path)[0] or "application/octet-stream",
            file_size_bytes=os.path.getsize(file_path) if os.path.exists(file_path) else 0,
        )

        # Extract with ffprobe if available
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                fmt = info.get("format", {})
                meta.duration_s = float(fmt.get("duration", 0))
                meta.bitrate_kbps = int(int(fmt.get("bit_rate", 0)) / 1000)

                for stream in info.get("streams", []):
                    if stream.get("codec_type") == "audio":
                        meta.sample_rate = int(stream.get("sample_rate", 0))
                        meta.channels = int(stream.get("channels", 0))
                        break
        except Exception:
            pass

        return meta

    def _transcribe(self, file_path: str) -> str:
        """音频转录。"""
        try:
            import whisper
            model = whisper.load_model(self._model)
            result = model.transcribe(file_path)
            return result["text"]
        except ImportError:
            return "[Transcription requires: pip install openai-whisper]"
        except Exception as e:
            return f"[Transcription error: {e}]"


class VideoProcessor(MediaProcessor):
    """视频处理器。

    提取关键帧、生成描述。

    Usage:
        processor = VideoProcessor()
        ctx = processor.process("demo.mp4")
        for caption in ctx.captions:
            print(caption)
    """

    def __init__(self, keyframe_interval_s: float = 2.0, max_keyframes: int = 10):
        self._keyframe_interval = keyframe_interval_s
        self._max_keyframes = max_keyframes
        self._image_processor = ImageProcessor()

    def process(self, file_path: str) -> MediaContext:
        ctx = MediaContext(media_type=MediaType.VIDEO)
        ctx.metadata = self.extract_metadata(file_path)
        ctx.captions = self._extract_keyframes(file_path)
        return ctx

    def extract_metadata(self, file_path: str) -> MediaMetadata:
        meta = MediaMetadata(
            file_path=file_path,
            media_type=MediaType.VIDEO,
            mime_type=mimetypes.guess_type(file_path)[0] or "application/octet-stream",
            file_size_bytes=os.path.getsize(file_path) if os.path.exists(file_path) else 0,
        )

        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", file_path],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                info = json.loads(result.stdout)
                fmt = info.get("format", {})
                meta.duration_s = float(fmt.get("duration", 0))
                meta.bitrate_kbps = int(int(fmt.get("bit_rate", 0)) / 1000)

                for stream in info.get("streams", []):
                    if stream.get("codec_type") == "video":
                        meta.width = int(stream.get("width", 0))
                        meta.height = int(stream.get("height", 0))
                        break
        except Exception:
            pass

        return meta

    def _extract_keyframes(self, file_path: str) -> List[str]:
        """提取视频关键帧。"""
        captions = []
        meta = self.extract_metadata(file_path)
        duration = meta.duration_s

        if duration == 0:
            return captions

        num_frames = min(
            int(duration / self._keyframe_interval),
            self._max_keyframes,
        )

        thumb_dir = Path(tempfile.gettempdir()) / "agentos_video_frames"
        thumb_dir.mkdir(exist_ok=True)

        for i in range(num_frames):
            timestamp = i * self._keyframe_interval
            frame_path = thumb_dir / f"frame_{uuid.uuid4().hex[:8]}.jpg"

            try:
                subprocess.run(
                    [
                        "ffmpeg", "-y", "-loglevel", "quiet",
                        "-ss", str(timestamp),
                        "-i", file_path,
                        "-vframes", "1",
                        "-q:v", "2",
                        str(frame_path),
                    ],
                    timeout=30,
                    check=True,
                )

                if frame_path.exists():
                    # Encode frame as base64
                    ctx = self._image_processor.process(str(frame_path))
                    captions.append(
                        f"[{self._format_time(timestamp)}] {ctx.text_description} "
                        f"base64:{ctx.base64_data[:50]}..."
                    )
                    # Cleanup frame file
                    frame_path.unlink(missing_ok=True)
            except Exception:
                pass

        return captions

    @staticmethod
    def _format_time(seconds: float) -> str:
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"


class DocumentProcessor(MediaProcessor):
    """文档处理器。

    从 PDF/DOCX 等文档中提取文本。

    Usage:
        processor = DocumentProcessor()
        ctx = processor.process("report.pdf")
        print(ctx.extracted_text[:500])
    """

    def process(self, file_path: str) -> MediaContext:
        ctx = MediaContext(media_type=MediaType.DOCUMENT)
        ctx.metadata = self.extract_metadata(file_path)
        ctx.extracted_text = self._extract_text(file_path)
        return ctx

    def extract_metadata(self, file_path: str) -> MediaMetadata:
        return MediaMetadata(
            file_path=file_path,
            media_type=MediaType.DOCUMENT,
            mime_type=mimetypes.guess_type(file_path)[0] or "application/octet-stream",
            file_size_bytes=os.path.getsize(file_path) if os.path.exists(file_path) else 0,
        )

    def _extract_text(self, file_path: str) -> str:
        """提取文档文本。"""
        ext = Path(file_path).suffix.lower()

        if ext == '.pdf':
            return self._extract_pdf(file_path)
        elif ext in ('.docx', '.doc'):
            return self._extract_docx(file_path)
        elif ext in ('.txt', '.md', '.py', '.json', '.yaml', '.xml', '.html', '.csv'):
            try:
                return Path(file_path).read_text(encoding='utf-8')
            except Exception:
                return Path(file_path).read_text(encoding='latin-1')
        else:
            return f"[Unsupported document format: {ext}]"

    def _extract_pdf(self, file_path: str) -> str:
        """从 PDF 中提取文本。"""
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(file_path)
            text_parts = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                text = page.get_text()
                if text.strip():
                    text_parts.append(f"--- Page {page_num + 1} ---\n{text}")
            doc.close()
            return "\n\n".join(text_parts) if text_parts else "[No extractable text in PDF]"
        except ImportError:
            try:
                result = subprocess.run(
                    ["pdftotext", file_path, "-"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode == 0:
                    return result.stdout
            except Exception:
                pass
            return "[PDF extraction requires: pip install PyMuPDF]"
        except Exception as e:
            return f"[PDF extraction error: {e}]"

    def _extract_docx(self, file_path: str) -> str:
        """从 DOCX 中提取文本。"""
        try:
            from docx import Document
            doc = Document(file_path)
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs) if paragraphs else "[No text in document]"
        except ImportError:
            return "[DOCX extraction requires: pip install python-docx]"
        except Exception as e:
            return f"[DOCX extraction error: {e}]"


# ── Multimodal Context Manager ──────────────


class MultimodalContextManager:
    """多模态上下文管理器。

    统一入口：接收文件路径，返回 MediaContext。

    Usage:
        mgr = MultimodalContextManager()
        ctx = mgr.load("photo.jpg")
        message = ctx.to_llm_message()
    """

    def __init__(self):
        self._detector = MediaDetector()
        self._processors: Dict[MediaType, MediaProcessor] = {
            MediaType.IMAGE: ImageProcessor(),
            MediaType.AUDIO: AudioProcessor(),
            MediaType.VIDEO: VideoProcessor(),
            MediaType.DOCUMENT: DocumentProcessor(),
        }

    def load(self, file_path: str) -> MediaContext:
        """加载并处理单个媒体文件。"""
        mtype = self._detector.detect(file_path)
        processor = self._processors.get(mtype)

        if not processor:
            ctx = MediaContext(media_type=MediaType.UNKNOWN)
            ctx.metadata = MediaMetadata(file_path=file_path, media_type=MediaType.UNKNOWN)
            ctx.extracted_text = f"[Unsupported media type: {mtype}]"
            return ctx

        return processor.process(file_path)

    def load_batch(self, file_paths: List[str]) -> List[MediaContext]:
        """批量加载。"""
        return [self.load(fp) for fp in file_paths]

    def load_as_message(self, file_path: str) -> dict:
        """加载并转换为 LLM 消息格式。"""
        return self.load(file_path).to_llm_message()

    def load_batch_as_messages(self, file_paths: List[str]) -> List[dict]:
        """批量加载为 LLM 消息。"""
        return [self.load_as_message(fp) for fp in file_paths]

    def register_processor(self, media_type: MediaType, processor: MediaProcessor) -> None:
        """注册自定义处理器。"""
        self._processors[media_type] = processor

    def analyze_directory(self, directory: str) -> Dict[str, List[str]]:
        """分析目录中的媒体文件分布。"""
        result: Dict[str, List[str]] = {
            "images": [],
            "audio": [],
            "video": [],
            "documents": [],
            "unknown": [],
        }

        dir_path = Path(directory)
        if not dir_path.exists():
            return result

        for file_path in dir_path.rglob("*"):
            if not file_path.is_file():
                continue

            mtype = self._detector.detect(str(file_path))

            if mtype == MediaType.IMAGE:
                result["images"].append(str(file_path))
            elif mtype == MediaType.AUDIO:
                result["audio"].append(str(file_path))
            elif mtype == MediaType.VIDEO:
                result["video"].append(str(file_path))
            elif mtype == MediaType.DOCUMENT:
                result["documents"].append(str(file_path))
            else:
                result["unknown"].append(str(file_path))

        return result


# ── Quick Start ─────────────────────────────


def create_multimodal_manager() -> MultimodalContextManager:
    """快速创建多模态上下文管理器。"""
    return MultimodalContextManager()


def quick_load(file_path: str) -> MediaContext:
    """快速加载单个文件。"""
    return MultimodalContextManager().load(file_path)
