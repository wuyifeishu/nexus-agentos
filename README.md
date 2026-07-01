
# Nexus AgentOS

**Production-grade multi-model agent framework. Build autonomous agents that run on anyone's machine — zero config, three providers, full observability.**

<p align="center">
  <a href="https://pypi.org/project/nexus-agentos/"><img src="https://img.shields.io/pypi/v/nexus-agentos?label=PyPI" alt="PyPI"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python"></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
  <a href="#"><img src="https://img.shields.io/badge/code%20style-ruff-000000" alt="Ruff"></a>
</p>

---

## Why AgentOS?

Most agent frameworks force you to wire up providers, retries, guardrails, and observability by hand. AgentOS ships them as first-class citizens — built into the core architecture, not bolted on.

| Capability | AgentOS | LangChain | CrewAI | AutoGen |
|---|---|---|---|---|
| **Multi-provider auto-detect** | ✅ Zero-config | ❌ Manual | ❌ | ❌ |
| **A2A Protocol** (Agent-to-Agent) | ✅ Native | ❌ | ❌ | ❌ |
| **MCP Protocol** (Tool integration) | ✅ Native | ✅ External | ❌ | ❌ |
| **Memory Pyramid** (STM→WM→LTM) | ✅ Built-in | ❌ | ❌ | ❌ |
| **HITL** (Human-in-the-Loop) | ✅ Built-in | ❌ | ❌ | ❌ |
| **Sandbox execution** | ✅ Process/Docker | ❌ | ❌ | ❌ |
| **Guardrails** (PII/toxicity/injection) | ✅ 6 built-in | ❌ | ❌ | ❌ |
| **OpenTelemetry bridge** | ✅ Native | ❌ | ❌ | ❌ |
| **DI Container** | ✅ Built-in | ❌ | ❌ | ❌ |
| **Streaming** (real-time) | ✅ | ✅ | ❌ | ❌ |
| **Agent Marketplace** | ✅ Built-in | ❌ | ❌ | ❌ |

---

## Quick Start

```bash
pip install nexus-agentos
```

### 1. Configure (recommended) — interactive wizard

```bash
agentos init
```

Guides you through choosing a provider (OpenAI / DeepSeek / Anthropic), pasting your API key, and tests the connection — no manual `export` needed.

### 2. Run a task

```bash
agentos "列出当前目录的文件"
```

### 3. Or try the demo (no API key needed)

```bash
agentos demo
```

> **Provider auto-detect**: AgentOS detects `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, or `ANTHROPIC_API_KEY` automatically. Run `agentos init` to set one up in 30 seconds.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     CLI / API Server                      │
├──────────────────────────────────────────────────────────┤
│  ToolAgent (autonomous multi-step reasoning)              │
├────────────┬────────────┬─────────────┬─────────────────┤
│  Guardrails│  Sandbox   │   Memory    │  Observability   │
│ (PII/Toxic │ (Process/  │ (STM→WM→LTM)│ (OTel Bridge +   │
│  /Injection│  Docker)   │             │  Cost Analytics) │
├────────────┴────────────┴─────────────┴─────────────────┤
│  LLM Providers: OpenAI │ DeepSeek │ Anthropic            │
│  A2A Protocol · MCP Protocol · Sequential Pipelines       │
│  Sub-agent Orchestration · DI Container · Plugin System  │
└──────────────────────────────────────────────────────────┘
```

---

## Standout Features

### 1. Provider Auto-Detection & Resiliency

No manual provider wiring. Set an env var, framework auto-detects. Built-in retry with exponential backoff and circuit breaker.

```python
from agentos.llm import create_provider

# Auto-detect from env
provider = create_provider()  # reads OPENAI_API_KEY → DeepSeek → Anthropic → mock fallback

# Or explicit
provider = create_provider("anthropic")  # claude-sonnet-4
```

### 2. A2A Protocol — Agent-to-Agent Communication

Agents communicate via Google’s A2A standard. Discover capabilities, negotiate tasks, exchange results — all with a typed protocol.

```python
from agentos.protocols.a2a import A2AProtocol, A2AMessage, AgentCard
from agentos.orchestration.a2a_router import A2ARouter

router = A2ARouter()
router.register(researcher_agent)
router.register(analyst_agent)

result = router.route(A2AMessage(
    sender="user",
    task="Research quantum computing advances, then analyze implications",
))
```

### 3. Memory Pyramid — Context That Scales

Three-tier memory architecture inspired by cognitive science:

| Tier | Purpose | Mechanism |
|------|---------|-----------|
| **Short-Term** | Current conversation | Sliding window |
| **Working** | Active context | Relevance-scored buffer |
| **Long-Term** | Persistent knowledge | Vector store + compression |

```python
from agentos.memory.pyramid import MemoryPyramid

memory = MemoryPyramid()
memory.store("User prefers Python over JavaScript", tier="long_term")
context = memory.retrieve("What language should I use?", top_k=5)
```

### 4. HITL — Human-in-the-Loop Approvals

Critical actions pause for human approval. Pre-built presets for finance, content moderation, and code execution.

```python
from agentos.hitl import HumanApprover, RiskPresets

approver = HumanApprover(preset=RiskPresets.FINANCE)
if approver.requires_approval(action="transfer", amount=5000):
    approver.request(action="Transfer $5000", context="Portfolio rebalance")
    # Agent pauses until human responds
```

### 5. Guardrails — Safety by Default

Six built-in guardrails validate inputs before they reach the LLM, and sanitize outputs before they reach the user.

```python
from agentos.guardrails import build_default_rules, GuardrailEngine

engine = GuardrailEngine(rules=build_default_rules())
result = engine.validate_input("Drop table users; --")  # blocked: code injection
```

| Rule | Purpose |
|------|---------|
| `PIIRule` | Redact emails, phones, SSNs |
| `KeywordBlockRule` | Block forbidden keywords |
| `CodeInjectionRule` | Detect SQL/command injection |
| `ToxicityRule` | Filter toxic/hateful content |
| `LengthLimitRule` | Cap input/output size |
| `RegexRule` | Custom pattern enforcement |

### 6. Sandbox Execution

Execute untrusted code in process-level or Docker sandboxes.

```python
from agentos.security import SandboxExecutor, SandboxMode

sandbox = SandboxExecutor(mode=SandboxMode.DOCKER)
result = sandbox.execute("print(1 + 2)")  # runs isolated, returns stdout+stderr
```

### 7. OpenTelemetry Bridge

Drop-in observability with existing OTel infrastructure.

```python
from agentos.observability import OTelBridge

bridge = OTelBridge(service_name="agentos-research-agent")
with bridge.trace("research_task"):
    result = agent.run("Research topic X")
# Traces appear in your existing Jaeger/Zipkin/Tempo
```

### 8. Swarm Coordination

Multi-agent topologies with handoff, debate, voting, and review-pass patterns.

```python
from agentos.swarm import SwarmCoordinator, SwarmTopology

swarm = SwarmCoordinator(topology=SwarmTopology.HIERARCHICAL)
swarm.add_agent("lead", lead_agent)
swarm.add_agent("worker_1", worker_1, parent="lead")
swarm.add_agent("worker_2", worker_2, parent="lead")
result = swarm.execute("Analyze quarterly report and generate summary")
```

---

## Python API

```python
from agentos.llm import create_provider
from agentos.llm.base import Tool, ToolParameter
from agentos.agent import ToolAgent, ToolExecutor, AgentConfig

# 1. Create provider (auto-detects from env)
provider = create_provider("openai")

# 2. Register tools
executor = ToolExecutor()
executor.register(
    Tool.from_function("get_weather", "Get city weather", {
        "city": ToolParameter(type="string", description="City name"),
    }),
    lambda city: f"{city}: 22°C sunny",
)

# 3. Create agent and run
agent = ToolAgent(provider, executor, config=AgentConfig(temperature=0.0))
result = agent.run("What's the weather in Tokyo?")

print(result.final_answer)       # "Tokyo: 22°C sunny"
print(f"Cost: ${result.total_cost_usd:.6f}")
print(f"Time: {result.total_duration_ms}ms")
```

## CLI

```
agentos <task>               Run a task with autonomous agent
agentos demo                 Run interactive demo
agentos serve                Start API server (port 8080)
agentos skills               List agent marketplace skills
agentos version              Show version
```

## Provider Auto-Detection

| Env Var | Provider | Default Model |
|---------|----------|---------------|
| `OPENAI_API_KEY` | OpenAI | `gpt-4o-mini` |
| `DEEPSEEK_API_KEY` | DeepSeek | `deepseek-chat` |
| `ANTHROPIC_API_KEY` | Anthropic | `claude-sonnet-4` |
| _(none set)_ | Mock | Demo mode |

---

## Installation

```bash
pip install nexus-agentos
```

Python 3.11+ required. Optional dependencies:

```bash
pip install "nexus-agentos[evaluation]"   # rouge-score, sentence-transformers
pip install "nexus-agentos[rag]"          # faiss-cpu, chromadb, tiktoken
pip install "nexus-agentos[dev]"          # pytest, mypy, ruff
```

---

## Examples

| Example | Description |
|---------|-------------|
| [`weather_agent.py`](agentos/agent/examples/weather_agent.py) | Multi-tool agent; weather + stock queries |
| [`llm_quickstart.py`](agentos/llm/examples/llm_quickstart.py) | Provider API basics |
| [`llm_chat_demo.py`](agentos/llm/examples/llm_chat_demo.py) | Multi-turn chat + streaming + function calling |

Full end-to-end examples in [`examples/`](examples/):

| Example | What it demonstrates |
|---------|---------------------|
| [`multi_agent_research.py`](examples/multi_agent_research.py) | Swarm + A2A + Memory Pyramid + streaming |
| [`file_ops_agent.py`](examples/file_ops_agent.py) | Sandbox + Guardrails + file tools + HITL |

---

## Roadmap

| Version | Focus |
|---------|-------|
| `1.4.x` | End-to-end examples, polished README, CLI improvements |
| `1.5.x` | Web UI dashboard, multi-modal (vision), RAG pipeline |
| `2.0.0` | Stable API, production deployment guides, community templates |

---

## License

MIT © AgentOS Team
