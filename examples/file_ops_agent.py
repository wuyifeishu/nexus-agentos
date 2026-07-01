"""
Secure File Operations Agent with Sandbox + Guardrails + HITL
==============================================================
Demonstrates: Sandbox execution, Guardrails (PII + Code Injection),
Human-in-the-Loop approvals, File tools.

What it does:
  1. Accepts a directory path to scan
  2. Reads all files through sandboxed file tools
  3. Guardrails check for PII and dangerous content
  4. HITL approval for any flagged files
  5. Generates a security audit report

Run:
  python examples/file_ops_agent.py
  python examples/file_ops_agent.py --dir /path/to/scan
  python examples/file_ops_agent.py --auto-approve  # skip HITL
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentos.llm.base import Tool, ToolParameter
from agentos.agent import ToolAgent, ToolExecutor, AgentConfig
from agentos.security.sandbox_executor import SandboxExecutor, SandboxMode
from agentos.guardrails.engine import GuardrailEngine, GuardrailResult, GuardrailAction
from agentos.guardrails.rules import PIIRule, CodeInjectionRule, build_default_rules
from agentos.hitl.approver import HumanApprover, RiskPresets


# ── Sandboxed File Tools ─────────────────────────────────────────


class SandboxedFileTools:
    """File operations that always go through the sandbox."""

    def __init__(self, sandbox: SandboxExecutor, safe_base: str):
        self.sandbox = sandbox
        self.safe_base = os.path.abspath(safe_base)

    def _validate_path(self, path: str) -> str:
        """Ensure path is within safe_base. Raises on escape attempt."""
        resolved = os.path.abspath(path)
        if not resolved.startswith(self.safe_base):
            raise ValueError(f"Path traversal blocked: {path} is outside {self.safe_base}")
        return resolved

    def list_directory(self, path: str) -> str:
        path = self._validate_path(path)
        result = self.sandbox.execute(f"ls -la {path}")
        return result.stdout or result.stderr or "(empty)"

    def read_file(self, file_path: str) -> str:
        file_path = self._validate_path(file_path)
        result = self.sandbox.execute(f"cat {file_path}")
        return result.stdout or result.stderr or "(empty)"

    def check_file_type(self, file_path: str) -> str:
        file_path = self._validate_path(file_path)
        result = self.sandbox.execute(f"file {file_path}")
        return result.stdout or "(unknown)"


# ── Guardrail Integration ────────────────────────────────────────


class SecurityScanner:
    """Scans file contents through guardrails."""

    def __init__(self):
        self.engine = GuardrailEngine(rules=build_default_rules())
        self.hitl = HumanApprover(preset=RiskPresets.CONTENT_MODERATION)

    def scan(self, file_path: str, content: str) -> dict[str, Any]:
        """Scan a single file. Returns dict with findings."""
        findings = {
            "path": file_path,
            "size": len(content),
            "pii_detected": False,
            "pii_details": [],
            "code_injection": False,
            "needs_approval": False,
            "approved": True,
        }

        # Unified guardrail check — evaluate once, inspect violations
        result = self.engine.check_input(content)
        if result.action == GuardrailAction.BLOCK:
            for v in result.violations:
                if "PII" in v:
                    findings["pii_detected"] = True
                    findings["pii_details"].append(v)
                    findings["needs_approval"] = True
                if "CodeInjection" in v:
                    findings["code_injection"] = True
                    findings["needs_approval"] = True

        # HITL if needed
        if findings["needs_approval"]:
            approved = self.hitl.request(
                action="read_sensitive_file",
                context=f"File {file_path} contains PII or potentially dangerous content. "
                         f"Risk: {findings['pii_details']}. Approve reading?",
            )
            findings["approved"] = approved

        return findings


# ── Main Pipeline ────────────────────────────────────────────────


def run_file_ops_agent(scan_dir: str, auto_approve: bool = False):
    """Run the full file operations security pipeline."""

    from agentos.llm import create_provider

    safe_base = os.path.abspath(scan_dir)
    print("=" * 65)
    print(f"  Nexus AgentOS — Secure File Operations Agent")
    print(f"  Scan directory: {safe_base}")
    print(f"  Sandbox mode:   Process")
    print(f"  HITL:           {'disabled (auto-approve)' if auto_approve else 'enabled'}")
    print("=" * 65)

    # Initialize sandbox
    sandbox = SandboxExecutor(mode=SandboxMode.PROCESS)
    scanner = SecurityScanner()
    tools = SandboxedFileTools(sandbox, safe_base)

    # Step 1: List directory
    print("\n[1/4] Listing directory contents...")
    listing = tools.list_directory(scan_dir)
    print(f"  Found:\n{listing[:500]}")

    # Step 2: Scan each file
    print("\n[2/4] Scanning files through guardrails...")
    all_findings = []
    lines = listing.split("\n")

    for line in lines[:20]:  # Limit to first 20 entries
        parts = line.split()
        if len(parts) < 9:
            continue
        filename = parts[-1]
        if filename in (".", ".."):
            continue
        file_path = os.path.join(safe_base, filename)

        try:
            content = tools.read_file(file_path)
            file_type = tools.check_file_type(file_path)
            findings = scanner.scan(file_path, content)

            risk = "HIGH" if findings["pii_detected"] or findings["code_injection"] else "LOW"
            flag = " ⚠" if findings["needs_approval"] else " ✓"
            status = "APPROVED" if findings["approved"] else "BLOCKED"

            print(f"  [{risk}]{flag} {filename:30s} {file_type.strip():20s} {status}")

            findings["file_type"] = file_type.strip()
            all_findings.append(findings)

        except ValueError as e:
            print(f"  [SKIP] {filename:30s} {e}")
        except Exception as e:
            print(f"  [ERROR] {filename:30s} {e}")

    # Step 3: Agent analysis
    print("\n[3/4] Agent analyzing results...")
    provider = create_provider()
    executor = ToolExecutor()
    agent = ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=AgentConfig(temperature=0.2),
        system_prompt=(
            "You are a security analyst. Given a file scan report, produce a concise "
            "security summary with:\n"
            "1. Total files scanned\n"
            "2. High-risk files (PII or code injection)\n"
            "3. Recommended actions\n"
            "Use bullet points. Be specific about which files need attention."
        ),
    )

    summary_prompt = f"Analyze this file scan report:\n\n"
    for f in all_findings:
        summary_prompt += f"- {f['path']}: PII={f['pii_detected']}, "
        summary_prompt += f"Injection={f['code_injection']}, "
        summary_prompt += f"Approved={f['approved']}, Type={f.get('file_type', 'N/A')}\n"

    agent_result = agent.run(summary_prompt)

    # Step 4: Generate report
    print("\n[4/4] Generating security audit report...")
    report_path = os.path.join(safe_base, "security_audit_report.md")
    report_lines = [
        "# Security Audit Report",
        f"Generated: {__import__('datetime').datetime.now().isoformat()}",
        f"Directory: {safe_base}",
        f"Sandbox: Process",
        "",
        "## Summary",
        f"- Files scanned: {len(all_findings)}",
        f"- High risk: {sum(1 for f in all_findings if f['pii_detected'] or f['code_injection'])}",
        f"- Blocked: {sum(1 for f in all_findings if not f['approved'])}",
        "",
        "## Findings",
    ]
    for f in all_findings:
        risk = "HIGH" if f["pii_detected"] or f["code_injection"] else "LOW"
        report_lines.append(f"- **[{risk}]** `{f['path']}` ({f.get('file_type', 'N/A')})")
        if f["pii_detected"]:
            report_lines.append(f"  - PII: {', '.join(f['pii_details'])}")
        if f["code_injection"]:
            report_lines.append(f"  - Code injection detected")
        report_lines.append(f"  - Status: {'Approved' if f['approved'] else 'Blocked'}")

    report_lines += ["", "## Agent Analysis", agent_result.final_answer]
    report_content = "\n".join(report_lines)

    with open(report_path, "w") as rf:
        rf.write(report_content)

    print(f"\n{'=' * 65}")
    print(f"  Audit Report: {report_path}")
    print(f"{'=' * 65}")
    print(f"\n{agent_result.final_answer}")

    return report_path


# ── Main ─────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Nexus AgentOS Secure File Operations Agent")
    parser.add_argument(
        "--dir", "-d",
        default=os.getcwd(),
        help="Directory to scan",
    )
    parser.add_argument(
        "--auto-approve", "-a",
        action="store_true",
        help="Skip HITL approvals",
    )
    args = parser.parse_args()

    run_file_ops_agent(scan_dir=args.dir, auto_approve=args.auto_approve)


if __name__ == "__main__":
    main()
