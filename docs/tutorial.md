# AgentOS Quickstart Tutorial

> Build your first production multi-agent system in 5 minutes.

---

## Installation

```bash
pip install nexus-agentos
```

---

## Tutorial 1: Your First Agent

```python
from agentos import Agent, OpenAIModel

# Create an agent with a tool
def get_weather(city: str) -> str:
    """Get weather for a city."""
    return f"Weather in {city}: 22°C, sunny"

agent = Agent(
    model=OpenAIModel("gpt-4o"),
    tools=[get_weather],
    system_prompt="You are a helpful assistant.",
)

# Run
response = await agent.run("What's the weather in Tokyo?")
print(response)  # "The weather in Tokyo is 22°C, sunny."
```

---

## Tutorial 2: Multi-Agent Swarm

```python
from agentos import Agent, Swarm, OpenAIModel

researcher = Agent(model=OpenAIModel("gpt-4o"), name="Researcher")
writer = Agent(model=OpenAIModel("gpt-4o"), name="Writer")
editor = Agent(model=OpenAIModel("gpt-4o"), name="Editor")

swarm = Swarm(agents=[researcher, writer, editor])

result = await swarm.run("Write a blog post about quantum computing")
print(result)
```

---

## Tutorial 3: Parallel Fan-Out

```python
from agentos import parallel_gather

async def process_chunk(chunk):
    return await agent.run(f"Summarize: {chunk}")

chunks = ["Text chunk 1", "Text chunk 2", "Text chunk 3"]

# All three run simultaneously
summaries = await parallel_gather(
    [process_chunk(c) for c in chunks],
    max_concurrency=3
)
print(summaries)  # 3 summaries, processed in parallel
```

---

## Tutorial 4: Workflow DSL (YAML)

Create `my_workflow.yaml`:

```yaml
name: research-pipeline
version: "1.0"
steps:
  - id: research
    type: task
    agent: researcher
    task: "Research the latest developments in {{ topic }}"
  - id: analyze
    type: task
    agent: analyst
    task: "Analyze the findings: {{ steps.research.output }}"
  - id: report
    type: task
    agent: writer
    task: "Write a report based on: {{ steps.analyze.output }}"
```

Run it:

```python
from agentos.workflow import WorkflowParser, WorkflowEngine

wf = WorkflowParser.parse_file("my_workflow.yaml")
ctx = await WorkflowEngine().execute(wf)
print(ctx.get("steps.report.output"))
```

---

## Tutorial 5: gRPC A2A Communication

```python
from agentos.protocols.grpc import (
    GrpcServer, GrpcServerConfig,
    GrpcClient, GrpcClientConfig,
    DefaultAgentService,
)

# Server
service = DefaultAgentService(agent_id="worker-1")
server = GrpcServer(service, GrpcServerConfig(port=50051))
await server.start()

# Client
client = GrpcClient(GrpcClientConfig())
response = await client.submit_task("worker-1", "Hello from client!")
print(response.result)  # Task acknowledged
```

---

## Tutorial 6: Memory with Reflection

```python
from agentos.memory.consolidation import ReflectionEngine

engine = ReflectionEngine()
await engine.add_memory("User prefers Python over JavaScript", importance=4)
await engine.add_memory("Project uses FastAPI", importance=3)

# Reflection automatically triggers when threshold is reached
insights = await engine.reflect()
print(insights)
# ["User is a Python developer focused on FastAPI projects"]
```

---

## Tutorial 7: HITL Approval Flow

```python
from agentos.hitl.gradio_ui import ApprovalDashboard, HITLUIBridge

bridge = HITLUIBridge()
dashboard = ApprovalDashboard(bridge)

@bridge.on_approval_required
async def require_approval(action):
    dashboard.show_request(action)
    decision = await bridge.wait_for_decision(timeout=300)
    return decision  # "approved" or "rejected"
```

---

## Next Steps

- [Cookbook](./cookbook.md) — End-to-end recipes
- [Workflow DSL Reference](../agentos/workflow/__init__.py)
- [gRPC A2A Protocol](../agentos/protocols/grpc.py)
- [Marketplace](./marketplace.md)
