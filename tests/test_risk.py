"""Tests for agentos.tools.risk."""

from agentos.tools.risk import (
    RISK_PRESETS,
    ToolRiskLevel,
    ToolRiskRating,
    get_risk_preset,
    infer_risk_level,
)


class TestToolRiskLevel:
    def test_values(self):
        assert ToolRiskLevel.LOW == "low"
        assert ToolRiskLevel.MEDIUM == "medium"
        assert ToolRiskLevel.HIGH == "high"
        assert ToolRiskLevel.CRITICAL == "critical"


class TestToolRiskRating:
    def test_defaults_to_medium(self):
        r = ToolRiskRating()
        assert r.level == ToolRiskLevel.MEDIUM
        assert r.reversible is True
        assert r.requires_approval is False
        assert r.financial_impact is False

    def test_requires_user_confirm_high(self):
        r = ToolRiskRating(level=ToolRiskLevel.HIGH)
        assert r.requires_user_confirm() is True

    def test_requires_user_confirm_critical(self):
        r = ToolRiskRating(level=ToolRiskLevel.CRITICAL)
        assert r.requires_user_confirm() is True

    def test_requires_user_confirm_approval(self):
        r = ToolRiskRating(level=ToolRiskLevel.LOW, requires_approval=True)
        assert r.requires_user_confirm() is True

    def test_requires_user_confirm_financial(self):
        r = ToolRiskRating(level=ToolRiskLevel.LOW, financial_impact=True)
        assert r.requires_user_confirm() is True

    def test_requires_user_confirm_low_safe(self):
        r = ToolRiskRating(level=ToolRiskLevel.LOW)
        assert r.requires_user_confirm() is False

    def test_custom_description(self):
        r = ToolRiskRating(level=ToolRiskLevel.HIGH, description="Delete config")
        assert r.description == "Delete config"


class TestRiskPresets:
    def test_get_read_preset(self):
        r = get_risk_preset("list_files")
        assert r is not None
        assert r.level == ToolRiskLevel.LOW

    def test_get_write_preset(self):
        r = get_risk_preset("write_file")
        assert r is not None
        assert r.level == ToolRiskLevel.MEDIUM

    def test_get_delete_preset(self):
        r = get_risk_preset("delete_file")
        assert r is not None
        assert r.level == ToolRiskLevel.HIGH
        assert r.requires_approval is True

    def test_get_critical_preset(self):
        r = get_risk_preset("format_disk")
        assert r is not None
        assert r.level == ToolRiskLevel.CRITICAL
        assert r.financial_impact is False

    def test_get_payment_preset(self):
        r = get_risk_preset("execute_payment")
        assert r is not None
        assert r.level == ToolRiskLevel.CRITICAL
        assert r.financial_impact is True

    def test_get_missing_returns_none(self):
        assert get_risk_preset("nonexistent_tool") is None

    def test_get_case_insensitive(self):
        r1 = get_risk_preset("DELETE_FILE")
        r2 = get_risk_preset("Delete_File")
        assert r1 is not None and r2 is not None
        assert r1.level == r2.level == ToolRiskLevel.HIGH


class TestInferRiskLevel:
    def test_preset_priority(self):
        r = infer_risk_level("delete_file")
        assert r.level == ToolRiskLevel.HIGH

    def test_infer_critical_by_keyword(self):
        r = infer_risk_level("sudo_exec")
        assert r.level == ToolRiskLevel.CRITICAL

    def test_infer_high_by_keyword(self):
        r = infer_risk_level("remove_user")
        assert r.level == ToolRiskLevel.HIGH

    def test_infer_medium_by_keyword(self):
        r = infer_risk_level("deploy_app")
        assert r.level == ToolRiskLevel.MEDIUM

    def test_infer_low_by_default(self):
        r = infer_risk_level("view_profile")
        assert r.level == ToolRiskLevel.LOW

    def test_description_assists_infer(self):
        r = infer_risk_level("cmd", tool_description="format the entire disk")
        assert r.level == ToolRiskLevel.CRITICAL

    def test_infer_returns_rating_instance(self):
        r = infer_risk_level("any_tool")
        assert isinstance(r, ToolRiskRating)

    def test_risks_presets_populated(self):
        assert len(RISK_PRESETS) >= 19
