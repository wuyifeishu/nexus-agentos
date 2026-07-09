"""
v1.10.0: Multimodal Provider — Vision & Audio abstraction layer.

Supports:
- VisionProvider: image→text (base class + OpenAI/VLLM adapters)
- AudioProvider: TTS + STT (base class + adapters)
- MultiModalMessage: unified multimodal message format
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ── Enums & Data Classes ──────────────────────────────────────────


class Modality(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


class ImageFormat(StrEnum):
    PNG = "png"
    JPEG = "jpeg"
    WEBP = "webp"
    GIF = "gif"
    SVG = "svg"


class AudioFormat(StrEnum):
    MP3 = "mp3"
    WAV = "wav"
    OGG = "ogg"
    FLAC = "flac"
    AAC = "aac"


@dataclass
class MultiModalContent:
    """A piece of multimodal content."""

    type: Modality
    text: str = ""
    data: bytes = field(default=b"", repr=False)
    data_url: str = ""  # data:image/png;base64,...
    mime_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def from_text(content: str) -> MultiModalContent:
        return MultiModalContent(type=Modality.TEXT, text=content)

    @staticmethod
    def from_path(path: str | Path) -> MultiModalContent:
        path = Path(path)
        data = path.read_bytes()
        ext = path.suffix.lower().lstrip(".")
        fmt_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "webp": "image/webp",
            "gif": "image/gif",
            "mp3": "audio/mpeg",
            "wav": "audio/wav",
            "ogg": "audio/ogg",
            "flac": "audio/flac",
        }
        mime = fmt_map.get(ext, "application/octet-stream")
        b64 = base64.b64encode(data).decode()
        modality = (
            Modality.IMAGE
            if mime.startswith("image/")
            else (Modality.AUDIO if mime.startswith("audio/") else Modality.TEXT)
        )
        return MultiModalContent(
            type=modality,
            data=data,
            data_url=f"data:{mime};base64,{b64}",
            mime_type=mime,
        )

    @staticmethod
    def from_bytes(data: bytes, mime_type: str = "image/png") -> MultiModalContent:
        b64 = base64.b64encode(data).decode()
        modality = (
            Modality.IMAGE
            if "image" in mime_type
            else (Modality.AUDIO if "audio" in mime_type else Modality.TEXT)
        )
        return MultiModalContent(
            type=modality,
            data=data,
            data_url=f"data:{mime_type};base64,{b64}",
            mime_type=mime_type,
        )


@dataclass
class MultiModalMessage:
    """A multimodal message with mixed content blocks."""

    role: str = "user"  # system / user / assistant
    content: list[MultiModalContent] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_text(self, text: str) -> MultiModalMessage:
        self.content.append(MultiModalContent.from_text(text))
        return self

    def add_image_path(self, path: str | Path) -> MultiModalMessage:
        self.content.append(MultiModalContent.from_path(path))
        return self

    def add_audio_path(self, path: str | Path) -> MultiModalMessage:
        self.content.append(MultiModalContent.from_path(path))
        return self

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI chat completion message format."""
        blocks: list[dict[str, Any]] = []
        for c in self.content:
            if c.type == Modality.TEXT:
                blocks.append({"type": "text", "text": c.text})
            elif c.type == Modality.IMAGE:
                blocks.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": c.data_url, "detail": "auto"},
                    }
                )
            elif c.type == Modality.AUDIO:
                blocks.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": base64.b64encode(c.data).decode(),
                            "format": c.mime_type.split("/")[-1] if c.mime_type else "wav",
                        },
                    }
                )
        return {"role": self.role, "content": blocks}

    def to_gemini_format(self) -> dict[str, Any]:
        """Convert to Gemini API message format."""
        parts: list[dict[str, Any]] = []
        for c in self.content:
            if c.type == Modality.TEXT:
                parts.append({"text": c.text})
            elif c.type == Modality.IMAGE:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": c.mime_type or "image/png",
                            "data": base64.b64encode(c.data).decode(),
                        }
                    }
                )
            elif c.type == Modality.AUDIO:
                parts.append(
                    {
                        "inline_data": {
                            "mime_type": c.mime_type or "audio/wav",
                            "data": base64.b64encode(c.data).decode(),
                        }
                    }
                )
        return {"role": "user" if self.role == "user" else "model", "parts": parts}


# ── Vision Provider ───────────────────────────────────────────────


@runtime_checkable
class VisionProvider(Protocol):
    """Protocol for vision providers (image → text)."""

    async def describe(self, image: MultiModalContent, prompt: str = "") -> str:
        """Describe an image. Returns text description."""
        ...

    async def ask(self, images: list[MultiModalContent], question: str) -> str:
        """Ask a question about one or more images."""
        ...


class OpenAIVisionProvider:
    """OpenAI GPT-4V / GPT-4o vision provider."""

    def __init__(self, api_key: str = "", model: str = "gpt-4o", base_url: str = ""):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

    async def describe(self, image: MultiModalContent, prompt: str = "") -> str:
        return await self.ask([image], prompt or "Describe this image in detail.")

    async def ask(self, images: list[MultiModalContent], question: str) -> str:
        import aiohttp

        message = MultiModalMessage(role="user")
        for img in images:
            message.content.append(img)
        message.add_text(question)
        body = message.to_openai_format()

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful vision assistant."},
                body,
            ],
            "max_tokens": 1024,
        }

        url = (
            f"{self.base_url}/chat/completions"
            if self.base_url
            else "https://api.openai.com/v1/chat/completions"
        )
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as resp:
                result = await resp.json()
                return result["choices"][0]["message"]["content"]


class LocalVisionProvider:
    """Local vision provider (placeholder for vLLM/Ollama)."""

    def __init__(self, endpoint: str = "http://localhost:11434", model: str = "llava"):
        self.endpoint = endpoint
        self.model = model

    async def describe(self, image: MultiModalContent, prompt: str = "") -> str:
        return await self.ask([image], prompt or "Describe this image.")

    async def ask(self, images: list[MultiModalContent], question: str) -> str:
        import aiohttp

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.endpoint}/api/generate",
                json={
                    "model": self.model,
                    "prompt": question,
                    "images": [img.data_url.split(",", 1)[1] for img in images if img.data_url],
                    "stream": False,
                },
            ) as resp:
                result = await resp.json()
                return result.get("response", "")


# ── Audio Provider ─────────────────────────────────────────────────


@runtime_checkable
class AudioProvider(Protocol):
    """Protocol for audio providers (TTS + STT)."""

    async def transcribe(self, audio: MultiModalContent, language: str = "") -> str:
        """Speech-to-text: transcribe audio to text."""
        ...

    async def synthesize(
        self, text: str, voice: str = "alloy", speed: float = 1.0
    ) -> MultiModalContent:
        """Text-to-speech: generate audio from text."""
        ...


class OpenAIAudioProvider:
    """OpenAI Whisper + TTS audio provider."""

    def __init__(self, api_key: str = "", tts_model: str = "tts-1", stt_model: str = "whisper-1"):
        self.api_key = api_key
        self.tts_model = tts_model
        self.stt_model = stt_model

    async def transcribe(self, audio: MultiModalContent, language: str = "") -> str:
        import aiohttp

        form = aiohttp.FormData()
        form.add_field("model", self.stt_model)
        form.add_field(
            "file",
            audio.data,
            filename=f"audio.{audio.mime_type.split('/')[-1] or 'wav'}",
            content_type=audio.mime_type or "audio/wav",
        )
        if language:
            form.add_field("language", language)

        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/audio/transcriptions", data=form, headers=headers
            ) as resp:
                result = await resp.json()
                return result.get("text", "")

    async def synthesize(
        self, text: str, voice: str = "alloy", speed: float = 1.0
    ) -> MultiModalContent:
        import aiohttp

        payload = {
            "model": self.tts_model,
            "input": text,
            "voice": voice,
            "speed": speed,
            "response_format": "mp3",
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.openai.com/v1/audio/speech", json=payload, headers=headers
            ) as resp:
                audio_data = await resp.read()
                return MultiModalContent.from_bytes(audio_data, "audio/mpeg")


class EdgeTTSProvider:
    """Microsoft Edge TTS (free, local)."""

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural"):
        self.voice = voice

    async def synthesize(self, text: str, voice: str = "", speed: float = 1.0) -> MultiModalContent:
        import edge_tts  # type: ignore[import-untyped]

        voice_name = voice or self.voice
        rate = f"{int((speed - 1.0) * 100):+d}%"
        communicate = edge_tts.Communicate(text, voice_name, rate=rate)
        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])
        audio_data = b"".join(audio_chunks)
        return MultiModalContent.from_bytes(audio_data, "audio/mpeg")


# ── MultiModal Client ─────────────────────────────────────────────


class MultiModalClient:
    """Unified multimodal client: vision + audio in one interface."""

    def __init__(
        self,
        vision: VisionProvider | None = None,
        audio: AudioProvider | None = None,
    ):
        self.vision = vision or LocalVisionProvider()
        self.audio = audio

    async def see(self, image_path: str | Path, question: str = "What's in this image?") -> str:
        """Look at an image and answer a question about it."""
        img = MultiModalContent.from_path(image_path)
        return await self.vision.ask([img], question)

    async def hear(self, audio_path: str | Path, language: str = "") -> str:
        """Transcribe audio to text."""
        if not self.audio:
            raise RuntimeError("No audio provider configured")
        audio = MultiModalContent.from_path(audio_path)
        return await self.audio.transcribe(audio, language)

    async def speak(self, text: str, voice: str = "alloy", speed: float = 1.0) -> MultiModalContent:
        """Generate speech from text."""
        if not self.audio:
            raise RuntimeError("No audio provider configured")
        return await self.audio.synthesize(text, voice, speed)
