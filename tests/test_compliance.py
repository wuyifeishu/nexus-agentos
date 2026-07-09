"""
Tests for MCP & A2A Compliance Suite (v1.14.7).
"""


import pytest

from agentos.protocols.compliance import (
    A2AComplianceSuite,
    ComplianceReport,
    ComplianceStatus,
    CrossFrameworkInterop,
    MCPComplianceSuite,
    run_all_compliance_tests,
)


class TestMCPCompliance:

    @pytest.mark.asyncio
    async def test_full_suite_runs(self):
        suite = MCPComplianceSuite()
        report = await suite.run_full_suite()
        assert isinstance(report, ComplianceReport)
        assert report.protocol == "mcp"
        assert report.total_tests > 0
        assert report.pass_rate > 0

    @pytest.mark.asyncio
    async def test_individual_tests(self):
        suite = MCPComplianceSuite()

        status, _ = await suite._test_mcp_01()
        assert status == ComplianceStatus.PASS

        status, _ = await suite._test_mcp_03()
        assert status == ComplianceStatus.PASS

        status, _ = await suite._test_mcp_05()
        assert status == ComplianceStatus.PASS

        status, _ = await suite._test_mcp_06()
        assert status == ComplianceStatus.PASS

        status, _ = await suite._test_mcp_08()
        assert status == ComplianceStatus.PASS

        status, _ = await suite._test_mcp_09()
        assert status == ComplianceStatus.PASS

        status, _ = await suite._test_mcp_14()
        assert status == ComplianceStatus.PASS

    @pytest.mark.asyncio
    async def test_report_format(self):
        suite = MCPComplianceSuite()
        report = await suite.run_full_suite()
        summary = report.to_summary()
        assert "protocol" in summary
        assert "total" in summary
        assert "passed" in summary
        assert "failed" in summary
        assert "pass_rate" in summary

    @pytest.mark.asyncio
    async def test_all_tests_either_pass_or_fail_or_skip(self):
        suite = MCPComplianceSuite()
        report = await suite.run_full_suite()
        for result in report.results:
            assert result.status in (ComplianceStatus.PASS, ComplianceStatus.FAIL, ComplianceStatus.SKIP)
            assert result.test_id.startswith("mcp-")
            assert result.name != ""

    @pytest.mark.asyncio
    async def test_pass_rate_calculation(self):
        suite = MCPComplianceSuite()
        report = await suite.run_full_suite()
        total = report.passed + report.failed + report.skipped
        assert report.total_tests == total

        if total > 0:
            assert report.pass_rate == report.passed / total


class TestA2ACompliance:

    @pytest.mark.asyncio
    async def test_full_suite_runs(self):
        suite = A2AComplianceSuite()
        report = await suite.run_full_suite()
        assert isinstance(report, ComplianceReport)
        assert report.protocol == "a2a"
        assert report.total_tests > 0
        assert report.pass_rate > 0

    @pytest.mark.asyncio
    async def test_agent_card_valid(self):
        suite = A2AComplianceSuite()
        status, msg = await suite._test_a2a_01()
        assert status == ComplianceStatus.PASS, msg

    @pytest.mark.asyncio
    async def test_task_lifecycle(self):
        suite = A2AComplianceSuite()
        status, msg = await suite._test_a2a_02()
        assert status == ComplianceStatus.PASS, msg

    @pytest.mark.asyncio
    async def test_message_bus(self):
        suite = A2AComplianceSuite()
        status, msg = await suite._test_a2a_03()
        assert status == ComplianceStatus.PASS, msg

    @pytest.mark.asyncio
    async def test_capability_negotiation(self):
        suite = A2AComplianceSuite()
        status, msg = await suite._test_a2a_07()
        assert status == ComplianceStatus.PASS, msg

    @pytest.mark.asyncio
    async def test_error_handling(self):
        suite = A2AComplianceSuite()
        status, msg = await suite._test_a2a_08()
        assert status == ComplianceStatus.PASS, msg

    @pytest.mark.asyncio
    async def test_all_tests_either_pass_or_fail_or_skip(self):
        suite = A2AComplianceSuite()
        report = await suite.run_full_suite()
        for result in report.results:
            assert result.status in (ComplianceStatus.PASS, ComplianceStatus.FAIL, ComplianceStatus.SKIP)
            assert result.test_id.startswith("a2a-")


class TestCrossFrameworkInterop:

    @pytest.mark.asyncio
    async def test_interop_checks(self):
        interop = CrossFrameworkInterop()
        results = await interop.run_interop_checks()

        assert "agentos_as_mcp_server" in results
        assert "agentos_as_mcp_client" in results
        assert "agentos_a2a_agent_card" in results
        assert "agentos_a2a_task" in results

    @pytest.mark.asyncio
    async def test_mcp_server_conforms(self):
        interop = CrossFrameworkInterop()
        result = await interop._check_mcp_server()
        assert result["status"] == "pass", result.get("error")

    @pytest.mark.asyncio
    async def test_agent_card_conforms(self):
        interop = CrossFrameworkInterop()
        result = await interop._check_agent_card()
        assert result["status"] == "pass", result.get("error")

    @pytest.mark.asyncio
    async def test_a2a_task_lifecycle(self):
        interop = CrossFrameworkInterop()
        result = await interop._check_a2a_task()
        assert result["status"] == "pass", result.get("missing_states", result.get("error"))


class TestRunAll:

    @pytest.mark.asyncio
    async def test_run_all(self):
        results = await run_all_compliance_tests()
        assert "mcp" in results
        assert "a2a" in results
        assert "interop" in results

        mcp_report = results["mcp"]
        a2a_report = results["a2a"]

        assert isinstance(mcp_report, ComplianceReport)
        assert isinstance(a2a_report, ComplianceReport)

        # At least 80% pass rate expected
        assert mcp_report.pass_rate >= 0.80, f"MCP pass rate too low: {mcp_report.pass_rate}"
        assert a2a_report.pass_rate >= 0.80, f"A2A pass rate too low: {a2a_report.pass_rate}"
