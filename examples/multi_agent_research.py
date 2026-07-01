
"""
Multi-Agent Research & Analysis Pipeline
=========================================
Demonstrates: Sequential agent pipeline, A2A Protocol, Memory Pyramid, Streaming, Provider auto-detect.

Architecture:
  ┌──────────────┐
  │ Orchestrator │  → Distributes tasks, aggregates results
  └─────┬────────┘
        │
   ┌────┴────┬──────────┐
   ▼         ▼          ▼
  Search   Analyst    Writer
  Agent    Agent      Agent
   │         │          │
   └────┬────┴──────────┘
        ▼
  Memory Pyramid (shared context)

What it does:
  1. Orchestrator delegates "research topic X" to SearchAgent
  2. SearchAgent fetches and summarizes sources → AnalystAgent
  3. AnalystAgent identifies trends, gaps, implications → WriterAgent
  4. WriterAgent produces a final report
  5. All agents share Memory Pyramid for context persistence

Run:
  python examples/multi_agent_research.py
  python examples/multi_agent_research.py --topic "quantum computing 2026"
  python examples/multi_agent_research.py --stream
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# Ensure package is importable (run from project root)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agentos.llm import create_provider
from agentos.llm.base import Tool, ToolParameter
from agentos.agent import ToolAgent, ToolExecutor, AgentConfig
from agentos.memory.pyramid import MemoryPyramid
from agentos.orchestration.a2a_router import A2ARouter
from agentos.protocols.a2a import A2AMessage, AgentCard


# ── Simulated Tools ──────────────────────────────────────────────


def web_search(query: str) -> str:
    """Simulated web search tool."""
    results = {
        "quantum computing 2026": (
            "1. IBM announces 2000+ qubit processor with record coherence time\n"
            "2. Google Quantum AI achieves error correction milestone on 100 logical qubits\n"
            "3. China launches quantum-encrypted satellite network covering APAC\n"
            "4. EU invests €5B in quantum infrastructure through Quantum Flagship 2.0\n"
            "5. Microsoft demonstrates topological qubit prototype"
        ),
        "quantum computing applications": (
            "1. Pharma: Pfizer accelerates drug discovery by 400x using quantum simulation\n"
            "2. Finance: JPMorgan deploys quantum Monte Carlo for portfolio optimization\n"
            "3. Materials: BASF discovers new catalyst material via quantum chemistry\n"
            "4. Logistics: DHL achieves 23% route optimization with quantum annealing"
        ),
        "quantum computing market": (
            "Market size 2026: $15.2B (CAGR 34.5%)\n"
            "Leaders: IBM (28%), Google (18%), IonQ (12%), Rigetti (8%)\n"
            "APAC fastest growing region at 42% YoY\n"
            "Venture funding: $4.8B in 2025, $6.2B projected 2026"
        ),
    }
    return results.get(query, f"No results found for: {query}")


# ── Agent Factory ────────────────────────────────────────────────


def _make_search_agent(provider) -> ToolAgent:
    executor = ToolExecutor()
    search_tool = Tool.from_function(
        name="web_search_tool",
        description="Search the web for information",
        parameters={"query": ToolParameter(type="string", description="Search query")},
    )
    executor.register(search_tool, web_search)
    return ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=AgentConfig(temperature=0.3),
        system_prompt=(
            "You are a research search agent. When given a topic, search for relevant "
            "information using the web_search_tool. Return a structured summary with "
            "sources labeled [1], [2], etc. Be thorough but concise."
        ),
    )


def _make_analyst_agent(provider) -> ToolAgent:
    executor = ToolExecutor()
    return ToolAgent(
        provider=provider,
        tool_executor=executor,
        config=AgentConfig(temperature=0.5),
        system_prompt=(
            "You are a strategic analyst. Given research findings, identify:\n"
            "1. Key trends and patterns\n"
            "2. Gaps in the current research\n"
            "3. Strategic implications\n"
            "4. Recommended actions\n"
            "Write in bullet points. Be analytical, not descriptive."
        ),
    )


def _make_writer_agent(provider) -> ToolAgent:
    return ToolAgent(
        provider=create_provider(),
        tool_executor=ToolExecutor(),
        config=AgentConfig(temperature=0.7),
        system_prompt=(
            "You are an executive report writer. Given research and analysis, produce "
            "a polished report with:\n"
            "- Executive Summary (3-4 sentences)\n"
            "- Key Findings (numbered list)\n"
            "- Analysis & Implications\n"
            "- Recommendations\n"
            "Use professional language. Max 500 words."
        ),
    )


# ── Swarm Orchestration ──────────────────────────────────────────


def run_swarm_pipeline(topic: str, stream: bool = False):
    """Run the full multi-agent pipeline."""

    provider = create_provider()

    # Shared memory pyramid
    memory = MemoryPyramid()

    # Create agents
    search_agent = _make_search_agent(provider)
    analyst_agent = _make_analyst_agent(provider)
    writer_agent = _make_writer_agent(provider)

    print("=" * 70)
    print(f"  Nexus AgentOS — Multi-Agent Research Pipeline")
    print(f"  Topic: {topic}")
    print("=" * 70)

    # Phase 1: Search
    print("\n[1/3] Search Agent gathering sources...")
    search_result = search_agent.run(f"Research: {topic}")
    memory.store(search_result.final_answer, tier="long_term")

    if stream:
        print(f"\n  Sources:\n{search_result.final_answer[:300]}...")

    # Phase 2: Analysis
    print("\n[2/3] Analyst Agent identifying trends & gaps...")
    analysis_prompt = (
        f"Analyze these research findings on '{topic}':\n\n"
        f"{search_result.final_answer}\n\n"
        f"Identify trends, gaps, implications."
    )
    analysis_result = analyst_agent.run(analysis_prompt)
    memory.store(analysis_result.final_answer, tier="long_term")

    # Phase 3: Report writing
    print("\n[3/3] Writer Agent producing final report...")
    report_prompt = (
        f"Write an executive report on '{topic}'.\n\n"
        f"RESEARCH:\n{search_result.final_answer}\n\n"
        f"ANALYSIS:\n{analysis_result.final_answer}"
    )
    report = writer_agent.run(report_prompt)

    # Phase 4: Validate with A2A
    print("\n[✓] Validating via A2A Protocol...")
    cards = [
        AgentCard(name="search", capabilities=["web_research"]),
        AgentCard(name="analyst", capabilities=["trend_analysis"]),
        AgentCard(name="writer", capabilities=["report_generation"]),
    ]
    router = A2ARouter()
    for c in cards:
        router.register(c)

    validation = router.route(A2AMessage(
        sender="orch",
        task=f"Verify report completeness for topic: {topic}",
        payload={"has_sources": bool(search_result.final_answer),
                  "has_analysis": bool(analysis_result.final_answer),
                  "has_report": bool(report.final_answer)},
    ))

    # Final output
    print("\n" + "=" * 70)
    print("  FINAL REPORT")
    print("=" * 70)
    print(f"\n{report.final_answer}\n")
    print("─" * 70)

    # Metrics
    total_cost = (search_result.total_cost_usd +
                  analysis_result.total_cost_usd +
                  report.total_cost_usd)
    total_time = (search_result.total_duration_ms +
                  analysis_result.total_duration_ms +
                  report.total_duration_ms)
    total_tokens = (search_result.total_tokens +
                    analysis_result.total_tokens +
                    report.total_tokens)

    print(f"\nPipeline Metrics:")
    print(f"  Total cost:   ${total_cost:.6f}")
    print(f"  Total time:   {total_time:.0f}ms")
    print(f"  Total tokens: {total_tokens}")
    print(f"  Steps:        {search_result.total_steps + analysis_result.total_steps + report.total_steps}")

    # Show memory stats
    stats = memory.stats()
    print(f"\nMemory Pyramid:")
    print(f"  Entries:      {stats.get('total_entries', 'N/A')}")
    print(f"  Tiers used:   {', '.join(stats.get('active_tiers', ['N/A']))}")
    print(f"  A2A check:    {validation.status}")

    return report.final_answer


# ── Main ─────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Nexus AgentOS Multi-Agent Research Pipeline")
    parser.add_argument(
        "--topic", "-t",
        default="quantum computing 2026",
        help="Research topic",
    )
    parser.add_argument(
        "--stream", "-s",
        action="store_true",
        help="Enable streaming output",
    )
    parser.add_argument(
        "--provider",
        default="",
        help="LLM provider: openai, deepseek, anthropic (auto-detect if empty)",
    )
    args = parser.parse_args()

    run_swarm_pipeline(topic=args.topic, stream=args.stream)


if __name__ == "__main__":
    main()
