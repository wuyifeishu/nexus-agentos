"""
summarize — Text summarization using extractive and heuristic methods.

Actions: summarize, extract_keywords, bullet_points, word_count
No external API required — pure Python.
"""

import re
from collections import Counter
from typing import Any


def run(
    action: str = "summarize",
    text: str = "",
    file_path: str = "",
    ratio: float = 0.3,
    **kwargs: Any,
) -> str:
    content = text
    if file_path:
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
        except FileNotFoundError:
            return f"[summarize] File not found: {file_path}"
        except Exception as e:
            return f"[summarize] Error reading file: {e}"

    if not content:
        return "[summarize] No text provided."

    if action == "word_count":
        words = re.findall(r"\b\w+\b", content.lower())
        wc = len(words)
        sc = len(re.split(r"[.!?]+", content))
        return f"Words: {wc}, Sentences: ~{sc}, Characters: {len(content)}"

    if action == "extract_keywords":
        words = re.findall(r"\b[a-zA-Z]{3,}\b", content.lower())
        stop = {
            "the",
            "and",
            "for",
            "that",
            "with",
            "this",
            "from",
            "have",
            "are",
            "not",
            "but",
            "was",
            "you",
            "all",
            "can",
            "has",
            "had",
            "been",
            "will",
            "they",
            "its",
            "their",
            "them",
            "our",
            "than",
            "then",
            "also",
            "into",
            "just",
            "about",
            "more",
            "some",
            "when",
            "your",
            "which",
            "make",
            "like",
            "what",
            "over",
            "such",
            "here",
            "were",
            "how",
            "one",
            "two",
        }
        filtered = [w for w in words if w not in stop]
        top = Counter(filtered).most_common(15)
        return "Top keywords: " + ", ".join(f"{w}({c})" for w, c in top)

    if action == "bullet_points":
        sentences = re.split(r"(?<=[.!?])\s+", content)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
        n = max(3, int(len(sentences) * ratio))
        return "[summarize] Bullet Points:\n" + "\n".join(f"- {s}" for s in sentences[:n])

    # Default: summarize (extractive)
    sentences = re.split(r"(?<=[.!?])\s+", content)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    if not sentences:
        return content[:500]

    n = max(2, int(len(sentences) * ratio))
    summary = " ".join(sentences[:n])
    if len(summary) > 1500:
        summary = summary[:1500] + "..."
    return summary


__all__ = ["run"]
