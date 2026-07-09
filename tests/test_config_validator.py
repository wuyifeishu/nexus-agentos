"""Tests for config_validator module."""

from agentos.config_validator import Severity, ValidationReport, validate_startup


class TestValidationReport:
    def test_empty_report_no_critical(self):
        report = ValidationReport()
        assert not report.has_critical

    def test_critical_detected(self):
        report = ValidationReport()
        report.add("disk", "no write", Severity.CRITICAL)
        assert report.has_critical

    def test_report_string(self):
        report = ValidationReport()
        report.add("env", "DB not set", Severity.WARNING, "Set DB URL")
        text = report.report()
        assert "WARNING" in text
        assert "DB not set" in text
        assert "Set DB URL" in text


class TestValidateStartup:
    def test_returns_report(self, tmp_path):
        """Basic validation in test environment returns a report."""
        report = validate_startup(data_dir=str(tmp_path / "data"), log_dir=str(tmp_path / "logs"))
        assert isinstance(report, ValidationReport)
        # In CI, external services won't be reachable → warnings OK, no critical
        assert not report.has_critical

    def test_creates_dirs(self, tmp_path):
        data = str(tmp_path / "data")
        logs = str(tmp_path / "logs")
        report = validate_startup(data_dir=data, log_dir=logs)
        assert not report.has_critical
