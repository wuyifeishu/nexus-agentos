"""AgentOS Multimodal Processing — v1.2.7.

- MultimodalManager: 统一多模态入口，自动路由到图像/音频/文档处理器。
- ImageProcessor / AudioProcessor / DocumentParser: 专用处理器。
"""

from agentos.multimodal.manager import (
    Modality,
    MultimodalBlock,
    ImageProcessor,
    AudioProcessor,
    DocumentParser,
    MultimodalManager,
)

__all__ = [
    "Modality",
    "MultimodalBlock",
    "ImageProcessor",
    "AudioProcessor",
    "DocumentParser",
    "MultimodalManager",
]
