"""v1.0.0-v1.10.0: Multimodal — Vision & Audio providers + manager."""
# Original exports (v1.2.7)
from agentos.multimodal.manager import (
    MultimodalManager,
    Modality,
)

# v1.10.0: Vision & Audio providers
from agentos.multimodal.provider import (
    ImageFormat, AudioFormat,
    MultiModalContent, MultiModalMessage,
    VisionProvider, OpenAIVisionProvider, LocalVisionProvider,
    AudioProvider, OpenAIAudioProvider, EdgeTTSProvider,
    MultiModalClient,
)

__all__ = [
    # Original
    "MultimodalManager",
    "Modality",
    # v1.10.0
    "ImageFormat", "AudioFormat",
    "MultiModalContent", "MultiModalMessage",
    "VisionProvider", "OpenAIVisionProvider", "LocalVisionProvider",
    "AudioProvider", "OpenAIAudioProvider", "EdgeTTSProvider",
    "MultiModalClient",
]
