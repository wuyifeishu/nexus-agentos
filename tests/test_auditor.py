"""Tests for agentos.security.auditor — security scanning."""

import json

from agentos.security.auditor import (
    AuditFinding,
    AuditReport,
    AuditSeverity,
    SecurityAuditor,
    _check_vuln_db,
    _parse_requirements,
    export_report,
    full_audit,
    scan_dependencies,
    scan_source,
)

# ── AuditFinding ──────────────────────────────────────────────────


class TestAuditFinding:
    def test_to_dict(self):
        finding = AuditFinding(
            id="TEST-001",
            category="test",
            severity=AuditSeverity.HIGH,
            message="test message",
            location="test.py:10",
            recommendation="fix it",
            cve="CVE-2024-0001",
        )
        d = finding.to_dict()
        assert d["id"] == "TEST-001"
        assert d["severity"] == "high"
        assert d["cve"] == "CVE-2024-0001"
        assert d["recommendation"] == "fix it"


# ── AuditReport ───────────────────────────────────────────────────


class TestAuditReport:
    def test_empty_report(self):
        report = AuditReport()
        assert report.critical == 0
        assert report.high == 0
        assert report.passed() is True

    def test_with_critical(self):
        report = AuditReport()
        report.findings.append(
            AuditFinding(id="C-1", category="test", severity=AuditSeverity.CRITICAL, message="bad")
        )
        assert report.critical == 1
        assert report.passed() is False

    def test_with_high(self):
        report = AuditReport()
        report.findings.append(
            AuditFinding(id="H-1", category="test", severity=AuditSeverity.HIGH, message="bad")
        )
        assert report.high == 1
        assert report.passed() is False

    def test_with_low_only_passes(self):
        report = AuditReport()
        report.findings.append(
            AuditFinding(id="L-1", category="test", severity=AuditSeverity.LOW, message="info")
        )
        assert report.low == 1
        assert report.passed() is True

    def test_summary(self):
        report = AuditReport()
        report.findings.extend([
            AuditFinding(id="C-1", category="test", severity=AuditSeverity.CRITICAL, message="bad"),
            AuditFinding(id="H-1", category="test", severity=AuditSeverity.HIGH, message="bad"),
            AuditFinding(id="M-1", category="test", severity=AuditSeverity.MEDIUM, message="warn"),
        ])
        report.scanned_files = 10
        report.scanned_deps = 5
        summary = report.summary()
        assert "1C / 1H / 1M / 0L" in summary
        assert "10 files" in summary
        assert "5 deps" in summary
        assert "FAILED" in summary

    def test_to_json(self):
        report = AuditReport()
        report.scanned_files = 1
        j = report.to_json()
        d = json.loads(j)
        assert "findings" in d
        assert d["summary"]["passed"] is True

    def test_to_markdown(self):
        report = AuditReport()
        report.findings.append(
            AuditFinding(id="X-1", category="test", severity=AuditSeverity.HIGH, message="bad",
                         recommendation="fix", cve="CVE-2024-0001")
        )
        md = report.to_markdown()
        assert "# Security Audit Report" in md
        assert "FAILED" in md
        assert "X-1" in md


# ── _parse_requirements ───────────────────────────────────────────


class TestParseRequirements:
    def test_simple(self):
        deps = _parse_requirements("requests==2.31.0\nflask>=2.0\n")
        assert ("requests", "==2.31.0") in deps
        assert ("flask", ">=2.0") in deps

    def test_comments_skipped(self):
        deps = _parse_requirements("# comment\nrequests==2.31.0\n--index-url ...")
        assert ("requests", "==2.31.0") in deps

    def test_complex_version(self):
        deps = _parse_requirements("django>=3.2,<4.0")
        assert len(deps) == 1
        assert deps[0][0] == "django"

    def test_blank_lines(self):
        deps = _parse_requirements("\n\nrequests\n\n")
        assert ("requests", "") in deps


# ── _check_vuln_db ────────────────────────────────────────────────


class TestCheckVulnDb:
    def test_django_vulnerable(self):
        findings = _check_vuln_db("django", "3.2.0")
        assert len(findings) >= 1
        assert any("CVE-2024-45230" in f.id for f in findings)

    def test_safe_package(self):
        findings = _check_vuln_db("safe-package", "1.0")
        assert findings == []


# ── scan_dependencies ─────────────────────────────────────────────


class TestScanDependencies:
    def test_scan_requirements_file(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("django==3.2.0\nsafe-pkg==1.0\n")
        report = scan_dependencies(req_file)
        assert report.scanned_deps == 2
        assert len(report.findings) >= 1

    def test_scan_nonexistent_file(self):
        report = scan_dependencies("/nonexistent/req.txt")
        assert report.scanned_deps == 0
        assert len(report.findings) == 1
        assert report.findings[0].severity == AuditSeverity.INFO


# ── scan_source ───────────────────────────────────────────────────


class TestScanSource:
    def test_clean_file(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("def add(a, b):\n    return a + b\n")
        report = scan_source(tmp_path)
        assert report.scanned_files == 1

    def test_eval_detected(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text("eval('1 + 1')\n")
        report = scan_source(tmp_path)
        evals = [fnd for fnd in report.findings if "eval" in fnd.id.lower()]
        assert len(evals) >= 1
        assert evals[0].severity == AuditSeverity.CRITICAL

    def test_exec_detected(self, tmp_path):
        f = tmp_path / "exec_bad.py"
        f.write_text("exec('print(1)')\n")
        report = scan_source(tmp_path)
        execs = [fnd for fnd in report.findings if "exec" in fnd.id.lower()]
        assert len(execs) >= 1

    def test_pickle_loads_detected(self, tmp_path):
        f = tmp_path / "pickle.py"
        f.write_text("import pickle\npickle.loads(data)\n")
        report = scan_source(tmp_path)
        pickles = [fnd for fnd in report.findings if "pickle" in fnd.id.lower()]
        assert len(pickles) >= 1

    def test_yaml_loads_detected(self, tmp_path):
        f = tmp_path / "yaml_bad.py"
        f.write_text("import yaml\nyaml.loads(data)\n")
        report = scan_source(tmp_path)
        yamls = [fnd for fnd in report.findings if "insecure" in fnd.id.lower()]
        assert len(yamls) >= 1

    def test_hardcoded_secret(self, tmp_path):
        f = tmp_path / "secrets.py"
        f.write_text('password = "super_secret_123"\n')
        report = scan_source(tmp_path)
        secrets = [fnd for fnd in report.findings if "HARDCODED" in fnd.id]
        assert len(secrets) >= 1

    def test_syntax_error_skipped(self, tmp_path):
        f = tmp_path / "broken.py"
        f.write_text("def broken(\n")  # syntax error
        report = scan_source(tmp_path)
        assert report.scanned_files >= 0  # shouldn't crash


# ── SecurityAuditor ───────────────────────────────────────────────


class TestSecurityAuditor:
    def test_init_with_paths(self, tmp_path):
        auditor = SecurityAuditor(req_path=tmp_path / "req.txt", source_dir=tmp_path)
        assert auditor.req_path == tmp_path / "req.txt"
        assert auditor.source_dir == tmp_path

    def test_scan_dependencies_with_path(self, tmp_path):
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("django==3.2.0\n")
        auditor = SecurityAuditor()
        report = auditor.scan_dependencies(req_path=req_file)
        assert report.scanned_deps == 1

    def test_scan_dependencies_no_path(self):
        auditor = SecurityAuditor()
        report = auditor.scan_dependencies()
        assert report.scanned_deps == 0

    def test_scan_source_with_paths(self, tmp_path):
        f = (tmp_path / "test.py")
        f.write_text("eval('1 + 1')\n")
        auditor = SecurityAuditor()
        report = auditor.scan_source(paths=[str(tmp_path)])
        assert report.scanned_files >= 1

    def test_scan_source_no_path(self):
        auditor = SecurityAuditor()
        report = auditor.scan_source()
        assert report.scanned_files == 0

    def test_full_audit_no_paths(self):
        auditor = SecurityAuditor()
        report = auditor.full_audit()
        assert isinstance(report, AuditReport)


# ── full_audit (module level) ─────────────────────────────────────


class TestFullAudit:
    def test_integration(self, tmp_path):
        source_dir = tmp_path / "src"
        source_dir.mkdir()
        (source_dir / "app.py").write_text("exec('bad')\n")
        req_file = tmp_path / "requirements.txt"
        req_file.write_text("django==3.2.0\nflask>=2.0\n")

        report = full_audit(source_dir=source_dir, req_path=req_file)
        assert report.scanned_files >= 1
        assert report.scanned_deps >= 1
        assert len(report.findings) >= 1


# ── export_report ─────────────────────────────────────────────────


class TestExportReport:
    def test_json_export(self):
        report = AuditReport()
        report.scanned_files = 3
        result = export_report(report, fmt="json")
        d = json.loads(result)
        assert "findings" in d

    def test_markdown_export(self):
        report = AuditReport()
        report.findings.append(
            AuditFinding(id="X-1", category="test", severity=AuditSeverity.CRITICAL,
                         message="bad", location="x.py:1", recommendation="fix")
        )
        result = export_report(report, fmt="md")
        assert "# Security Audit Report" in result
        assert "**Summary**" in result


# ── _DangerousVisitor ─────────────────────────────────────────────


class TestDangerousVisitor:
    def test_empty_file_no_findings(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("# nothing\n")
        report = scan_source(tmp_path)
        assert report.findings == []

    def test_multiple_findings_in_one_file(self, tmp_path):
        f = tmp_path / "multiple.py"
        f.write_text("eval('x')\nexec('y')\n")
        report = scan_source(tmp_path)
        assert len(report.findings) >= 2
