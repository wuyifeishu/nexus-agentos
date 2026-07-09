"""Citation tracing for RAG pipeline.

Tracks which source documents contributed to generated text,
enabling answer provenance and fact-checking.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Citation:
    """A single citation linking generated text to a source chunk."""

    chunk_id: str
    chunk_text: str
    source_doc: str = ""  # source document identifier
    relevance_score: float = 0.0
    context: str = ""  # surrounding context window
    start_char: int = 0  # position in generated answer
    end_char: int = 0


@dataclass
class CitationReport:
    """Complete citation analysis for a generated response."""

    answer: str = ""
    citations: list[Citation] = field(default_factory=list)
    source_count: int = 0
    coverage: float = 0.0  # fraction of answer covered by citations
    unused_sources: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "num_citations": len(self.citations),
            "source_count": self.source_count,
            "coverage": self.coverage,
            "citations": [
                {
                    "chunk_id": c.chunk_id,
                    "source_doc": c.source_doc,
                    "relevance": c.relevance_score,
                    "span": f"{c.start_char}-{c.end_char}",
                    "text_preview": c.chunk_text[:200],
                }
                for c in self.citations
            ],
        }


class CitationTracer:
    """Track which retrieved chunks contributed to an answer.

    Two modes:
    - token_overlap: Match answer spans to chunk texts by token overlap.
    - explicit: Parse answer for explicit citation markers like [1], [doc1].
    """

    def __init__(
        self,
        mode: str = "token_overlap",
        min_overlap: int = 20,  # minimum characters of overlap
        overlap_ratio: float = 0.3,  # minimum overlap ratio
    ):
        self.mode = mode
        self.min_overlap = min_overlap
        self.overlap_ratio = overlap_ratio

    def trace(
        self,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> CitationReport:
        """Trace answer back to source chunks.

        Args:
            answer: Generated text response.
            sources: Retrieved chunks with 'text', 'score', 'index' keys.

        Returns:
            CitationReport with matched citations.
        """
        if self.mode == "explicit":
            citations = self._trace_explicit(answer, sources)
        else:
            citations = self._trace_overlap(answer, sources)

        # Compute coverage
        if answer and citations:
            covered_chars = self._compute_covered_chars(answer, citations)
            coverage = covered_chars / len(answer)
        else:
            coverage = 0.0

        # Find unused sources
        used_ids = {c.chunk_id for c in citations}
        unused = [
            f"chunk_{s.get('index', i)}"
            for i, s in enumerate(sources)
            if f"chunk_{s.get('index', i)}" not in used_ids
        ]

        return CitationReport(
            answer=answer,
            citations=citations,
            source_count=len(sources),
            coverage=round(coverage, 3),
            unused_sources=unused,
        )

    def _trace_overlap(
        self,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> list[Citation]:
        """Find answer spans that overlap with source chunks."""
        citations = []

        for i, src in enumerate(sources):
            chunk_text = src.get("text", "")
            if not chunk_text:
                continue

            chunk_id = f"chunk_{src.get('index', i)}"

            # Find longest common substrings
            matches = self._find_substring_matches(answer, chunk_text)
            for start, end in matches:
                citations.append(
                    Citation(
                        chunk_id=chunk_id,
                        chunk_text=chunk_text,
                        source_doc=src.get("source", src.get("document", "")),
                        relevance_score=src.get("score", 0.0),
                        context=self._get_context(chunk_text, start, end),
                        start_char=start,
                        end_char=end,
                    )
                )

        return citations

    def _trace_explicit(
        self,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> list[Citation]:
        """Parse explicit citation markers like [1], [source1], [doc:1]."""
        citations = []

        # Match [N], [docN], [source N]
        pattern = r"\[(?:doc|source|ref)?\s*(\d+)\]"
        matches = re.finditer(pattern, answer, re.IGNORECASE)

        for m in matches:
            ref_num = int(m.group(1))
            if 1 <= ref_num <= len(sources):
                src = sources[ref_num - 1]
                citations.append(
                    Citation(
                        chunk_id=f"chunk_{src.get('index', ref_num - 1)}",
                        chunk_text=src.get("text", ""),
                        source_doc=src.get("source", ""),
                        relevance_score=src.get("score", 0.0),
                        context=src.get("text", "")[:500],
                        start_char=m.start(),
                        end_char=m.end(),
                    )
                )

        return citations

    def _find_substring_matches(
        self,
        answer: str,
        chunk: str,
    ) -> list[tuple[int, int]]:
        """Find spans in answer that match substrings from chunk."""
        matches = []
        min_len = min(self.min_overlap, len(chunk) // 4)

        # Use sliding window of sentences/phrases from chunk
        sentences = re.split(r"(?<=[.!?。！？])\s+", chunk)
        for sent in sentences:
            sent = sent.strip()
            if len(sent) < min_len:
                continue

            pos = answer.find(sent)
            if pos >= 0:
                matches.append((pos, pos + len(sent)))
            else:
                # Try shorter windows
                window = max(min_len, len(sent) // 2)
                step = window // 2
                for start in range(0, len(sent) - window + 1, step):
                    sub = sent[start : start + window]
                    pos = answer.find(sub)
                    if pos >= 0:
                        matches.append((pos, pos + len(sub)))
                        break

        return self._merge_overlapping(matches)

    def _merge_overlapping(
        self,
        spans: list[tuple[int, int]],
    ) -> list[tuple[int, int]]:
        """Merge overlapping citation spans."""
        if not spans:
            return []

        sorted_spans = sorted(spans)
        merged = [sorted_spans[0]]

        for span in sorted_spans[1:]:
            last = merged[-1]
            if span[0] <= last[1]:
                merged[-1] = (last[0], max(last[1], span[1]))
            else:
                merged.append(span)

        return merged

    def _get_context(self, chunk_text: str, start: int, end: int) -> str:
        """Get surrounding context around a match."""
        ctx_start = max(0, start - 100)
        ctx_end = min(len(chunk_text), end + 100)
        return chunk_text[ctx_start:ctx_end]

    def _compute_covered_chars(
        self,
        answer: str,
        citations: list[Citation],
    ) -> int:
        """Compute total characters covered by citations."""
        if not citations:
            return 0

        coverage = [False] * len(answer)
        for c in citations:
            for i in range(max(0, c.start_char), min(c.end_char, len(answer))):
                coverage[i] = True

        return sum(coverage)

    def build_attribution_map(
        self,
        answer: str,
        sources: list[dict[str, Any]],
    ) -> str:
        """Build HTML attribution map for the answer.

        Wraps cited spans in <cite> tags with source references.
        """
        citations = self._trace_overlap(answer, sources)

        # Sort citations by start position and apply in reverse to preserve indices
        citations.sort(key=lambda c: c.start_char, reverse=True)

        result = answer
        for c in citations:
            prefix = result[: c.start_char]
            cited = result[c.start_char : c.end_char]
            suffix = result[c.end_char :]

            source_id = c.chunk_id.replace("chunk_", "")
            cited_wrapped = (
                f'<cite data-source="{c.source_doc}" '
                f'data-chunk="{source_id}" '
                f'data-score="{c.relevance_score:.2f}">'
                f"{cited}</cite>"
            )
            result = prefix + cited_wrapped + suffix

        return result


def hash_chunk_id(text: str, index: int) -> str:
    """Generate a stable chunk ID from text content."""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"chunk_{index}_{digest}"
