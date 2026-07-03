"""
CSP — Content Security Policy builder and validator.

Supports:
    - Fluent API for building CSP headers
    - Source lists (self, none, urls, hashes, nonces, strict-dynamic)
    - Directives: default-src, script-src, style-src, img-src, connect-src, font-src,
      object-src, media-src, frame-src, frame-ancestors, form-action, base-uri,
      report-uri, report-to, upgrade-insecure-requests, block-all-mixed-content,
      sandbox, worker-src, manifest-src, prefetch-src, navigate-to
    - Nonce generation
    - Validation of directives
    - Serialize to header string
"""

from __future__ import annotations

import secrets
from typing import List, Optional, Set, Union


# ============================================================================
# Constants
# ============================================================================

ALL_DIRECTIVES = frozenset({
    "default-src", "script-src", "script-src-elem", "script-src-attr",
    "style-src", "style-src-elem", "style-src-attr",
    "img-src", "connect-src", "font-src", "object-src", "media-src",
    "frame-src", "frame-ancestors", "form-action", "base-uri",
    "report-uri", "report-to", "sandbox",
    "worker-src", "manifest-src", "prefetch-src", "navigate-to",
    "child-src", "fenced-frame-src",
    "upgrade-insecure-requests", "block-all-mixed-content",
    "require-trusted-types-for",
})

FLAG_DIRECTIVES = frozenset({"upgrade-insecure-requests", "block-all-mixed-content"})

KEYWORD_SOURCES = frozenset({
    "'self'", "'none'", "'strict-dynamic'",
    "'unsafe-inline'", "'unsafe-eval'",
    "'unsafe-hashes'", "'unsafe-allow-redirects'",
    "'wasm-unsafe-eval'",
})


# ============================================================================
# Nonce
# ============================================================================

def generate_nonce(length: int = 32) -> str:
    """Generate a cryptographically random base64 nonce."""
    return secrets.token_urlsafe(length)


# ============================================================================
# CSP
# ============================================================================

class CSP:
    """Fluent Content Security Policy builder.

    Usage:
        csp = (CSP()
            .default_src("'self'")
            .script_src("'self'", "'strict-dynamic'", nonce=generate_nonce())
            .style_src("'self'", "https://fonts.googleapis.com")
            .img_src("*")
            .upgrade_insecure_requests()
        )

        header = csp.to_header()
        # default-src 'self'; script-src 'self' 'strict-dynamic' 'nonce-abc123'; ...
    """

    def __init__(self):
        self._directives: dict = {}

    # ---------- Directive setters ----------

    def default_src(self, *sources: str) -> CSP:
        return self._set("default-src", *sources)

    def script_src(self, *sources: str, nonce: Optional[str] = None, hashes: Optional[List[str]] = None) -> CSP:
        if nonce:
            sources = sources + (f"'nonce-{nonce}'",)
        if hashes:
            sources = sources + tuple(h for h in hashes)
        return self._set("script-src", *sources)

    def script_src_elem(self, *sources: str, nonce: Optional[str] = None) -> CSP:
        if nonce:
            sources = sources + (f"'nonce-{nonce}'",)
        return self._set("script-src-elem", *sources)

    def script_src_attr(self, *sources: str) -> CSP:
        return self._set("script-src-attr", *sources)

    def style_src(self, *sources: str, nonce: Optional[str] = None) -> CSP:
        if nonce:
            sources = sources + (f"'nonce-{nonce}'",)
        return self._set("style-src", *sources)

    def style_src_elem(self, *sources: str, nonce: Optional[str] = None) -> CSP:
        if nonce:
            sources = sources + (f"'nonce-{nonce}'",)
        return self._set("style-src-elem", *sources)

    def style_src_attr(self, *sources: str) -> CSP:
        return self._set("style-src-attr", *sources)

    def img_src(self, *sources: str) -> CSP:
        return self._set("img-src", *sources)

    def connect_src(self, *sources: str) -> CSP:
        return self._set("connect-src", *sources)

    def font_src(self, *sources: str) -> CSP:
        return self._set("font-src", *sources)

    def object_src(self, *sources: str) -> CSP:
        return self._set("object-src", *sources)

    def media_src(self, *sources: str) -> CSP:
        return self._set("media-src", *sources)

    def frame_src(self, *sources: str) -> CSP:
        return self._set("frame-src", *sources)

    def frame_ancestors(self, *sources: str) -> CSP:
        return self._set("frame-ancestors", *sources)

    def form_action(self, *sources: str) -> CSP:
        return self._set("form-action", *sources)

    def base_uri(self, *sources: str) -> CSP:
        return self._set("base-uri", *sources)

    def worker_src(self, *sources: str) -> CSP:
        return self._set("worker-src", *sources)

    def child_src(self, *sources: str) -> CSP:
        return self._set("child-src", *sources)

    def manifest_src(self, *sources: str) -> CSP:
        return self._set("manifest-src", *sources)

    def prefetch_src(self, *sources: str) -> CSP:
        return self._set("prefetch-src", *sources)

    def navigate_to(self, *sources: str) -> CSP:
        return self._set("navigate-to", *sources)

    def sandbox(self, *flags: str) -> CSP:
        value = " ".join(flags) if flags else ""
        self._directives["sandbox"] = value
        return self

    def report_uri(self, *uris: str) -> CSP:
        return self._set("report-uri", *uris)

    def report_to(self, group: str) -> CSP:
        self._directives["report-to"] = group
        return self

    # ---------- Flags ----------

    def upgrade_insecure_requests(self) -> CSP:
        self._directives["upgrade-insecure-requests"] = ""
        return self

    def block_all_mixed_content(self) -> CSP:
        self._directives["block-all-mixed-content"] = ""
        return self

    # ---------- Utility ----------

    def _set(self, directive: str, *sources: str) -> CSP:
        existing = self._directives.get(directive)
        if isinstance(existing, list):
            existing.extend(sources)
        else:
            self._directives[directive] = list(sources)
        return self

    def to_header(self) -> str:
        """Serialize to CSP header string."""
        parts = []
        for directive, value in self._directives.items():
            if value == "":
                parts.append(directive)
            elif isinstance(value, list):
                sources_str = " ".join(value)
                parts.append(f"{directive} {sources_str}")
            else:
                parts.append(f"{directive} {value}")
        return "; ".join(parts)

    def to_dict(self) -> dict:
        return dict(self._directives)

    @classmethod
    def parse(cls, header: str) -> CSP:
        """Parse a CSP header string into a CSP builder."""
        csp = cls()
        for part in header.split(";"):
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            directive = tokens[0]
            if directive in FLAG_DIRECTIVES:
                csp._directives[directive] = ""
            elif directive == "sandbox":
                csp._directives[directive] = " ".join(tokens[1:]) if len(tokens) > 1 else ""
            elif directive == "report-to":
                csp._directives[directive] = tokens[1] if len(tokens) > 1 else ""
            else:
                csp._directives[directive] = tokens[1:]
        return csp

    @classmethod
    def is_valid_directive(cls, name: str) -> bool:
        return name in ALL_DIRECTIVES

    @classmethod
    def strict_policy(cls, nonce: Optional[str] = None) -> CSP:
        """Pre-built strict CSP with nonce or hash-based approach."""
        csp = cls()
        csp.base_uri("'self'")
        csp.default_src("'self'")
        csp.object_src("'none'")
        if nonce:
            csp.script_src("'strict-dynamic'", nonce=nonce)
            csp.style_src(nonce=nonce)
        else:
            csp.script_src("'self'")
            csp.style_src("'self'")
        csp.img_src("*", "data:")
        csp.font_src("'self'", "data:")
        csp.connect_src("'self'")
        csp.frame_ancestors("'none'")
        return csp
