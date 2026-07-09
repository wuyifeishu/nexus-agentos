---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 3e9b297b16411e0e0848fc0302358070_4c43a1af747011f1b2f55254006c9bbf
    ReservedCode1: L3/qViRzmTta/iFYzpaa0FpXw4uxuVsUAtWCl2l9QRL9xsChpMusrpNfbdNq/IzAtr4QaLSdrDYEDEYSw9LnpQp9d5UyJ8o7Gxs1fQDctKAOJWELBA+MraiU+ViKh/IuQQn+0YwqYUlGzObqU3WoAHgVpveCbfIsYTVaNOCnutyU2ZZ+pwNcjpp5510=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 3e9b297b16411e0e0848fc0302358070_4c43a1af747011f1b2f55254006c9bbf
    ReservedCode2: L3/qViRzmTta/iFYzpaa0FpXw4uxuVsUAtWCl2l9QRL9xsChpMusrpNfbdNq/IzAtr4QaLSdrDYEDEYSw9LnpQp9d5UyJ8o7Gxs1fQDctKAOJWELBA+MraiU+ViKh/IuQQn+0YwqYUlGzObqU3WoAHgVpveCbfIsYTVaNOCnutyU2ZZ+pwNcjpp5510=
---



# AgentOS Quick Start

## 安装

```bash
pip install agentos
```

## 最小示例

```python
from agentos import AgentLoop, LoopConfig

loop = AgentLoop(LoopConfig(max_iterations=3))
result = loop.run("用一句话解释什么是递归")
print(result.output)
```

## 配置

```python
from agentos import AgentOSConfig, load_config

config = load_config("agentos.yaml")
print(config.models)
```
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
