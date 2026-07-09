"""AgentOS Security Auditor — automated vulnerability scanning and code analysis.

Audits dependencies and source patterns for common security issues.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# ── Severity ──────────────────────────────────────────────────────────────────


class AuditSeverity(Enum):
    """Severity level for security audit findings."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class AuditFinding:
    """A single security finding from an audit scan.

    Attributes:
        id: Unique finding identifier.
        category: Finding category (e.g., injection, hardcoded_secret).
        severity: Severity level.
        message: Human-readable description.
        location: File path and line reference.
        recommendation: Suggested remediation.
        cve: Optional CVE identifier if known.
    """

    id: str
    category: str
    severity: AuditSeverity
    message: str
    location: str = ""
    recommendation: str = ""
    cve: str | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "category": self.category,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location,
            "recommendation": self.recommendation,
            "cve": self.cve,
        }


@dataclass
class AuditReport:
    """Aggregated report of all audit findings across scanned resources.

    Attributes:
        findings: List of individual findings.
        scanned_files: Number of files scanned.
        scanned_deps: Number of dependencies checked.
    """

    findings: list[AuditFinding] = field(default_factory=list)
    scanned_files: int = 0
    scanned_deps: int = 0

    @property
    def critical(self) -> int:
        return sum(1 for f in self.findings if f.severity == AuditSeverity.CRITICAL)

    @property
    def high(self) -> int:
        return sum(1 for f in self.findings if f.severity == AuditSeverity.HIGH)

    @property
    def medium(self) -> int:
        return sum(1 for f in self.findings if f.severity == AuditSeverity.MEDIUM)

    @property
    def low(self) -> int:
        return sum(1 for f in self.findings if f.severity == AuditSeverity.LOW)

    def passed(self) -> bool:
        return self.critical == 0 and self.high == 0

    def summary(self) -> str:
        return (
            f"Audit: {self.critical}C / {self.high}H / {self.medium}M / {self.low}L "
            f"across {self.scanned_files} files, {self.scanned_deps} deps — "
            f"{'PASSED' if self.passed() else 'FAILED'}"
        )

    def to_dict(self) -> dict:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "summary": {
                "critical": self.critical,
                "high": self.high,
                "medium": self.medium,
                "low": self.low,
                "passed": self.passed(),
                "scanned_files": self.scanned_files,
                "scanned_deps": self.scanned_deps,
            },
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict(), indent=2, default=str)

    def to_markdown(self) -> str:
        lines = [
            "# Security Audit Report",
            "",
            f"- **Scanned files**: {self.scanned_files}",
            f"- **Scanned dependencies**: {self.scanned_deps}",
            f"- **Result**: {'PASSED' if self.passed() else 'FAILED'}",
            "",
            "| Severity | Count |",
            "|----------|-------|",
            f"| CRITICAL | {self.critical} |",
            f"| HIGH     | {self.high} |",
            f"| MEDIUM   | {self.medium} |",
            f"| LOW      | {self.low} |",
            "",
        ]
        if self.findings:
            lines.append("## Findings")
            lines.append("")
            for f in self.findings:
                lines.append(f"- **[{f.severity.value.upper()}]** `{f.id}` — {f.message}")
                if f.recommendation:
                    lines.append(f"  → {f.recommendation}")
        return "\n".join(lines)


# ── Built‑in checkers ────────────────────────────────────────────────────────

# Known-vulnerable version patterns (illustrative)
_VULN_PATTERNS: list[dict] = [
    {"pkg": "django", "range": "<4.2.15", "cve": "CVE-2024-45230", "severity": "HIGH"},
    {"pkg": "requests", "range": "<2.32.0", "cve": "CVE-2024-35195", "severity": "MEDIUM"},
    {"pkg": "cryptography", "range": "<42.0.0", "cve": "CVE-2024-26130", "severity": "HIGH"},
    {"pkg": "jinja2", "range": "<3.1.4", "cve": "CVE-2024-34064", "severity": "MEDIUM"},
    {"pkg": "aiohttp", "range": "<3.9.4", "cve": "CVE-2024-30251", "severity": "HIGH"},
]

# Dangerous AST patterns
_DANGEROUS_PATTERNS: list[dict] = [
    {
        "name": "eval-use",
        "node": "Call",
        "attr": "func.id",
        "match": "eval",
        "severity": "CRITICAL",
        "msg": "eval() detected — arbitrary code execution risk",
    },
    {
        "name": "exec-use",
        "node": "Call",
        "attr": "func.id",
        "match": "exec",
        "severity": "CRITICAL",
        "msg": "exec() detected — arbitrary code execution risk",
    },
    {
        "name": "pickle-load",
        "node": "Call",
        "attr": "func.attr",
        "match": "loads",
        "parent_attr": "func.value.id",
        "parent_match": "pickle",
        "severity": "HIGH",
        "msg": "pickle.loads() on untrusted data may execute arbitrary code",
    },
    {
        "name": "hardcoded-secret",
        "node": "Assign",
        "attr": "targets[0].id",
        "match_re": r"(?i)(password|secret|api_key|token|access_key)\s*$",
        "severity": "HIGH",
        "msg": "Potential hard-coded secret",
    },
    {
        "name": "shell-true",
        "node": "Call",
        "attr": "keywords",
        "match_expr": "subprocess.Popen(… shell=True) or os.system() — command injection risk",
        "severity": "HIGH",
        "msg": "shell=True detected — command injection risk when input is untrusted",
    },
    {
        "name": "insecure-deserialization",
        "node": "Call",
        "attr": "func.attr",
        "match": "loads",
        "parent_attr": "func.value.id",
        "parent_match": "yaml",
        "severity": "HIGH",
        "msg": "yaml.load() without SafeLoader — arbitrary code execution risk",
    },
    {
        "name": "md5-hash",
        "node": "Call",
        "attr": "func.attr",
        "match": "md5",
        "parent_attr": "func.value.id",
        "parent_match": "hashlib",
        "severity": "LOW",
        "msg": "MD5 is cryptographically broken; use SHA-256",
    },
]


# ── Dependency scanner ───────────────────────────────────────────────────────


def _parse_requirements(content: str) -> list[tuple[str, str]]:
    """Parse requirements.txt into (pkg, version_spec) pairs."""
    deps: list[tuple[str, str]] = []
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        # Normalise: requests==2.31.0  ->  ('requests', '2.31.0')
        m = re.match(r"^([a-zA-Z0-9_.-]+)\s*([><=!~]+\s*[\d.*]+(?:,\s*[><=!~]+\s*[\d.*]+)*)?", line)
        if m:
            pkg = m.group(1).lower()
            ver = (m.group(2) or "").strip()
            deps.append((pkg, ver))
    return deps


def _check_vuln_db(pkg: str, version_spec: str) -> list[AuditFinding]:
    findings: list[AuditFinding] = []
    for entry in _VULN_PATTERNS:
        if entry["pkg"] != pkg:
            continue
        findings.append(
            AuditFinding(
                id=f"VULN-{entry['cve']}",
                category="dependency",
                severity=AuditSeverity(entry["severity"].lower()),
                message=f"{pkg}{version_spec and ' ' + version_spec} is vulnerable — {entry['cve']}",
                recommendation=f"Upgrade to {entry['range'].lstrip('<')}+",
                cve=entry["cve"],
            )
        )
    return findings


def scan_dependencies(req_path: str | Path) -> AuditReport:
    """Scan a requirements.txt or pyproject.toml for known-vulnerable dependencies."""
    req_path = Path(req_path)
    report = AuditReport()

    if not req_path.exists():
        report.findings.append(
            AuditFinding(
                id="DEP-001",
                category="dependency",
                severity=AuditSeverity.INFO,
                message=f"Dependency file not found: {req_path}",
            )
        )
        return report

    content = req_path.read_text()
    deps = _parse_requirements(content)
    report.scanned_deps = len(deps)

    for pkg, ver in deps:
        report.findings.extend(_check_vuln_db(pkg, ver))

    return report


# ── Source scanner ────────────────────────────────────────────────────────────


class _DangerousVisitor(ast.NodeVisitor):
    """AST visitor that flags dangerous code patterns (exec, eval, subprocess, etc.)."""

    def __init__(self) -> None:
        self.findings: list[AuditFinding] = []

    def _match(self, node: ast.AST, pattern: dict, lineno: int) -> AuditFinding | None:
        name = pattern["name"]
        severity = AuditSeverity(pattern["severity"].lower())

        if "match_re" in pattern:
            attr_path = pattern["attr"]
            try:
                val = eval(f"node.{attr_path}", {"node": node})
            except Exception:
                return None
            if isinstance(val, str) and re.search(pattern["match_re"], val):
                return AuditFinding(
                    id=f"SRC-{name.upper()}",
                    category="source",
                    severity=severity,
                    message=pattern["msg"],
                    location=f"line {lineno}",
                    recommendation="Remove or replace with a safe alternative",
                )
            return None

        if "match_expr" in pattern:
            # Special-case shell=True
            for kw in getattr(node, "keywords", []):
                if kw.arg == "shell" and getattr(kw.value, "value", None) is True:
                    return AuditFinding(
                        id=f"SRC-{name.upper()}",
                        category="source",
                        severity=severity,
                        message=pattern["msg"],
                        location=f"line {lineno}",
                        recommendation="Avoid shell=True; use list args",
                    )
            return None

        # Standard attr match
        attr_path = pattern["attr"]
        match_val = pattern["match"]
        parent_attr = pattern.get("parent_attr")
        parent_match = pattern.get("parent_match")

        try:
            val = eval(f"node.{attr_path}", {"node": node})
        except Exception:
            return None

        if parent_attr is not None:
            try:
                pval = eval(f"node.{parent_attr}", {"node": node})
            except Exception:
                return None
            if pval == parent_match and val == match_val:
                return AuditFinding(
                    id=f"SRC-{name.upper()}",
                    category="source",
                    severity=severity,
                    message=pattern["msg"],
                    location=f"line {lineno}",
                    recommendation="Remove or replace with a safe alternative",
                )
        elif isinstance(val, str) and val == match_val:
            return AuditFinding(
                id=f"SRC-{name.upper()}",
                category="source",
                severity=severity,
                message=pattern["msg"],
                location=f"line {lineno}",
                recommendation="Remove or replace with a safe alternative",
            )
        return None

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        for pat in _DANGEROUS_PATTERNS:
            if pat["node"] == "Call":
                finding = self._match(node, pat, node.lineno)
                if finding:
                    self.findings.append(finding)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        for pat in _DANGEROUS_PATTERNS:
            if pat["node"] == "Assign":
                finding = self._match(node, pat, node.lineno)
                if finding:
                    self.findings.append(finding)
        self.generic_visit(node)


def scan_source(source_dir: str | Path) -> AuditReport:
    """AST-based source code security scan."""
    source_dir = Path(source_dir)
    report = AuditReport()
    py_files = list(source_dir.rglob("*.py"))

    for fpath in py_files:
        try:
            tree = ast.parse(fpath.read_text())
        except SyntaxError:
            continue
        visitor = _DangerousVisitor()
        visitor.visit(tree)
        report.findings.extend(visitor.findings)
        report.scanned_files += 1

    return report


# ── Security Auditor class ────────────────────────────────────────────────────


class SecurityAuditor:
    """High-level security auditor that orchestrates dependency and source scanning."""

    def __init__(self, req_path: str | Path | None = None, source_dir: str | Path | None = None):
        self.req_path: Path | None = Path(req_path) if req_path else None
        self.source_dir: Path | None = Path(source_dir) if source_dir else None

    def scan_dependencies(self, req_path: str | Path | None = None) -> AuditReport:
        """Scan dependencies for known vulnerabilities."""
        path = Path(req_path) if req_path else self.req_path
        if not path or not path.exists():
            return AuditReport()
        return scan_dependencies(path)

    def scan_source(self, paths: list[str | Path] | None = None) -> AuditReport:
        """AST-based source code security scan."""
        if paths:
            report = AuditReport()
            for p in paths:
                r = scan_source(p)
                report.findings.extend(r.findings)
                report.scanned_files += r.scanned_files
            return report
        if not self.source_dir:
            return AuditReport()
        return scan_source(self.source_dir)

    def full_audit(
        self, source_dir: str | Path | None = None, req_path: str | Path | None = None
    ) -> AuditReport:
        """Run dependency + source audit and merge results."""
        sd = source_dir or self.source_dir
        rp = req_path or self.req_path
        if not sd or not rp:
            return AuditReport()
        return full_audit(Path(sd), Path(rp))


# ── Full audit (module-level) ─────────────────────────────────────────────────


def full_audit(
    source_dir: str | Path,
    req_path: str | Path,
) -> AuditReport:
    """Run dependency + source audit and merge results."""
    dep_report = scan_dependencies(req_path)
    src_report = scan_source(source_dir)

    merged = AuditReport(
        findings=dep_report.findings + src_report.findings,
        scanned_files=src_report.scanned_files,
        scanned_deps=dep_report.scanned_deps,
    )
    return merged


# ── Report export ─────────────────────────────────────────────────────────────


def export_report(report: AuditReport, fmt: str = "json") -> str:
    """Export audit report to JSON or Markdown."""
    if fmt == "json":
        return json.dumps(report.to_dict(), indent=2)
    # Markdown
    lines = [
        "# Security Audit Report",
        "",
        f"**Summary**: {report.summary()}",
        "",
        "| Severity | Count |",
        "|----------|-------|",
        f"| Critical | {report.critical} |",
        f"| High     | {report.high} |",
        f"| Medium   | {report.medium} |",
        f"| Low      | {report.low} |",
        "",
        "## Findings",
        "",
    ]
    for f in sorted(report.findings, key=lambda x: (4 - list(AuditSeverity).index(x.severity))):
        lines.append(f"- **[{f.severity.value.upper()}]** {f.message}  ")
        if f.location:
            lines.append(f"  *Location*: {f.location}")
        if f.recommendation:
            lines.append(f"  *Fix*: {f.recommendation}")
        if f.cve:
            lines.append(f"  *CVE*: {f.cve}")
        lines.append("")

    return "\n".join(lines)
