# AgentOS Cookbook

> Production-tested recipes for common multi-agent scenarios.

---

## Recipe 1: CI/CD Code Review Bot

**Problem**: Automate PR reviews with multiple specialist agents.

```python
from agentos import Agent, Swarm, parallel_gather
from agentos.workflow import WorkflowParser, WorkflowEngine

wf_yaml = """
name: pr-review-pipeline
version: "1.0"
steps:
  - id: fetch_diff
    type: task
    agent: github-agent
    task: "Get diff for PR {{ pr_number }} from {{ repo }}"
  - id: parallel_review
    type: parallel
    children:
      - id: security_check
        type: task
        agent: security-agent
        task: "Check for security vulnerabilities: {{ steps.fetch_diff.output }}"
      - id: style_check
        type: task
        agent: style-agent
        task: "Check code style: {{ steps.fetch_diff.output }}"
      - id: perf_check
        type: task
        agent: perf-agent
        task: "Check performance: {{ steps.fetch_diff.output }}"
  - id: consolidate
    type: task
    agent: reviewer
    task: "Merge review feedback: security={{ steps.security_check.output }}, style={{ steps.style_check.output }}, perf={{ steps.perf_check.output }}"
"""

wf = WorkflowParser.parse_dict(yaml.safe_load(wf_yaml))
ctx = await WorkflowEngine().execute(wf)
# Post ctx.get("steps.consolidate.output") to PR as comment
```

---

## Recipe 2: Research Paper Generator

**Problem**: Automatically research, draft, review, and polish a paper.

```python
from agentos import Agent, OpenAIModel
from agentos.workflow import WorkflowTemplates, WorkflowEngine

# Define specialized agents
researcher = Agent(
    model=OpenAIModel("gpt-4o"),
    system_prompt="You are a research scientist. Find and synthesize information.",
    tools=[web_search, arxiv_search],
)
drafter = Agent(
    model=OpenAIModel("gpt-4o"),
    system_prompt="You write clear, academic prose from research notes.",
)
reviewer = Agent(
    model=OpenAIModel("claude-3-opus"),
    system_prompt="You critically review academic papers for rigor and clarity.",
)

# Build sequential pipeline
wf = WorkflowTemplates.sequential(
    name="paper-generator",
    agent_ids=["researcher", "drafter", "reviewer"],
    task_template="Process the paper on topic: {{ topic }}",
)
wf.variables["topic"] = "Advancements in Multi-Agent Reinforcement Learning"

ctx = await WorkflowEngine().execute(wf)
```

---

## Recipe 3: Real-Time Data Pipeline

**Problem**: Ingest, process, analyze streaming data with fault tolerance.

```python
from agentos.orchestration.distributed import RayAgentActor, PlacementStrategy
from agentos.memory.consolidation import ReflectionEngine

# Deploy agents across Ray cluster
actor = RayAgentActor.options(
    num_cpus=2,
    placement_strategy=PlacementStrategy.SPREAD,
).remote(agent_config)

# Stream processing with retry loop
from agentos.workflow import WorkflowTemplates

wf = WorkflowTemplates.retry_loop(
    name="stream-processor",
    agent_id="data-processor",
    task="Process batch {{ batch_id }}",
    max_retries=5,
)

for batch_id in range(100):
    try:
        await WorkflowEngine().execute(wf)
    except Exception:
        logger.error(f"Batch {batch_id} failed, will retry next cycle")
```

---

## Recipe 4: Multi-Modal Document Assistant

**Problem**: Process mixed documents (PDFs, images, audio) through a single agent.

```python
from agentos.multimodal import (
    ImageProcessor, DocumentProcessor, AudioProcessor,
    MediaDetector, to_llm_message,
)

async def process_any_file(file_path: str) -> str:
    media_type = MediaDetector.detect(file_path)

    if media_type == "image":
        processor = ImageProcessor()
        data = await processor.process(file_path)
    elif media_type == "document":
        processor = DocumentProcessor()
        data = await processor.process(file_path)
    elif media_type == "audio":
        processor = AudioProcessor()
        data = await processor.process(file_path)
    else:
        raise ValueError(f"Unsupported type: {media_type}")

    message = to_llm_message(data, provider="openai")
    return await agent.run(message)
```

---

## Recipe 5: Human-in-the-Loop Approval Pipeline

**Problem**: Require human approval for high-stakes actions before execution.

```python
from agentos.hitl.gradio_ui import ApprovalDashboard, HITLUIBridge
from agentos.orchestration.distributed import RayAgentActor

bridge = HITLUIBridge()
dashboard = ApprovalDashboard(bridge)

# Agent actions that need approval
DANGER_THRESHOLD = 10000  # $10k

async def execute_with_approval(agent, action, amount):
    if amount > DANGER_THRESHOLD:
        # Pause and request human approval
        approved = await bridge.request_approval(
            action=f"Execute {action} for ${amount:,}",
            details={"amount": amount, "action": action},
            timeout=300,
        )
        if not approved:
            return "Action rejected by human operator"

    return await agent.run(f"Execute: {action}")
```

---

## Recipe 6: Marketplace Agent Installation

**Problem**: Discover and install pre-built agents from the marketplace.

```python
from agentos.marketplace import (
    MarketplaceManager, MarketSearchQuery,
    TemplateCategory, RemoteMarketClient,
)

manager = MarketplaceManager(
    remote_clients=[RemoteMarketClient("https://marketplace.agentos.dev")],
)

# Search for coding agents
results = await manager.search(MarketSearchQuery(
    keywords="code review",
    category=TemplateCategory.CODING,
    min_rating=4.0,
))

for r in results:
    print(f"{r.template.name} ({r.template.stars} stars) - {r.template.description[:80]}")

# Install the top result
path = await manager.install(results[0].template.id)
print(f"Installed to {path}")
```

---

## Recipe 7: Observability Dashboard

**Problem**: Monitor agent performance and health in production.

```python
from agentos.observability import Tracer, MetricsRegistry, StructuredLogger

# Initialize tracing
tracer = Tracer(service_name="my-agent-cluster")
metrics = MetricsRegistry()

# Instrument agent calls
@tracer.trace("agent.run")
async def traced_run(agent, prompt):
    with metrics.timer("agent_latency"):
        metrics.increment("agent_requests")
        result = await agent.run(prompt)
        metrics.observe("output_tokens", len(result))
        return result

# Export to Prometheus
metrics.start_http_server(port=9090)
logger = StructuredLogger().bind(service="my-agent-cluster")
logger.info("Observability stack ready", metrics_endpoint=":9090")
```

---

## Recipe 8: Self-Evolving Agent (Sandbox)

**Problem**: Allow agents to write and test code safely.

```python
from agentos.sandbox import DockerSandbox, CodeValidator

# Validate code before execution
code = await agent.run("Write a Python function to calculate Fibonacci")
is_safe, issues = CodeValidator.validate(code)
if not is_safe:
    raise ValueError(f"Unsafe code: {issues}")

# Execute in sandbox
async with DockerSandbox(image="python:3.11-slim") as sandbox:
    result = await sandbox.run(code, timeout=30)
    print(f"Output: {result.stdout}")
    print(f"Error: {result.stderr}")
```

---

## Deployment Patterns

### Single Node (Development)

```bash
pip install nexus-agentos
python -c "from agentos import Agent; ..."
```

### Distributed Cluster (Production)

```bash
# Start Ray head node
ray start --head --port=6379

# Start worker nodes
ray start --address=<head-ip>:6379

# Deploy agents
python -m agentos.orchestration.distributed --num-agents 10
```

### Docker Compose

```yaml
services:
  agentos-head:
    image: nexus-agentos:1.14.4
    command: ray start --head
    ports:
      - "8265:8265"  # Dashboard
      - "9090:9090"  # Prometheus metrics

  agentos-worker:
    image: nexus-agentos:1.14.4
    command: ray start --address=agentos-head:6379
    deploy:
      replicas: 3
```
