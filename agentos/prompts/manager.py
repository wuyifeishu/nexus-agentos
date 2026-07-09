"""
AgentOS v0.30 Prompt模板管理 — 版本化Prompt仓库。
支持模板继承、变量注入、A/B测试、回滚。
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class PromptTemplate:
    """Prompt 模板。"""

    name: str
    version: str
    template: str
    variables: list[str] = field(default_factory=list)
    description: str = ""
    parent: str | None = None
    created_at: str = ""
    metadata: dict = field(default_factory=dict)

    def render(self, **kwargs) -> str:
        """渲染模板，注入变量。"""
        result = self.template
        for var in self.variables:
            value = kwargs.get(var, kwargs.get(f"{{{var}}}", f"{{{{{var}}}}}"))
            result = result.replace(f"{{{{{var}}}}}", str(value))
        return result


class PromptRegistry:
    """Prompt模板注册中心。"""

    def __init__(self, storage_path: str = ""):
        self._templates: dict[str, dict[str, PromptTemplate]] = {}
        self.storage_path = storage_path
        if storage_path and os.path.exists(storage_path):
            self._load()

    def register(self, template: PromptTemplate):
        if template.name not in self._templates:
            self._templates[template.name] = {}
        template.created_at = template.created_at or datetime.now().isoformat()
        self._templates[template.name][template.version] = template
        self._save()

    def get(self, name: str, version: str = "latest") -> PromptTemplate | None:
        versions = self._templates.get(name, {})
        if not versions:
            return None
        if version == "latest":
            sorted_vers = sorted(versions.keys(), key=lambda v: [int(x) for x in v.split(".")])
            return versions[sorted_vers[-1]]
        return versions.get(version)

    def get_version(self, name: str, version: str) -> PromptTemplate | None:
        return self._templates.get(name, {}).get(version)

    def list_templates(self) -> list[dict]:
        result = []
        for name, versions in self._templates.items():
            sorted_vers = sorted(versions.keys(), key=lambda v: [int(x) for x in v.split(".")])
            result.append(
                {
                    "name": name,
                    "versions": sorted_vers,
                    "latest": sorted_vers[-1],
                    "description": versions[sorted_vers[-1]].description,
                    "variables": versions[sorted_vers[-1]].variables,
                }
            )
        return result

    def render(self, name: str, version: str = "latest", **kwargs) -> str:
        tmpl = self.get(name, version)
        if not tmpl:
            raise ValueError(f"Template '{name}' not found")
        return tmpl.render(**kwargs)

    def rollback(self, name: str, target_version: str):
        if name not in self._templates:
            raise ValueError(f"Template '{name}' not found")
        versions = self._templates[name]
        if target_version not in versions:
            raise ValueError(f"Version '{target_version}' not found for '{name}'")
        sorted_vers = sorted(versions.keys(), key=lambda v: [int(x) for x in v.split(".")])
        latest_ver = sorted_vers[-1]
        if latest_ver == target_version:
            return
        # 回滚：基于目标版本创建新版本
        target = versions[target_version]
        new_ver_parts = [int(x) for x in latest_ver.split(".")]
        new_ver_parts[-1] += 1
        new_ver = ".".join(str(x) for x in new_ver_parts)
        rolled = PromptTemplate(
            name=name,
            version=new_ver,
            template=target.template,
            variables=list(target.variables),
            description=f"Rollback from {latest_ver} to {target_version}",
            parent=target_version,
        )
        self.register(rolled)
        return rolled

    def _save(self):
        if not self.storage_path:
            return
        data = {}
        for name, versions in self._templates.items():
            data[name] = {}
            for ver, tmpl in versions.items():
                data[name][ver] = {
                    "template": tmpl.template,
                    "variables": tmpl.variables,
                    "description": tmpl.description,
                    "parent": tmpl.parent,
                    "created_at": tmpl.created_at,
                    "metadata": tmpl.metadata,
                }
        os.makedirs(os.path.dirname(self.storage_path) or ".", exist_ok=True)
        with open(self.storage_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _load(self):
        with open(self.storage_path) as f:
            data = json.load(f)
        for name, versions in data.items():
            if name not in self._templates:
                self._templates[name] = {}
            for ver, vdata in versions.items():
                self._templates[name][ver] = PromptTemplate(
                    name=name,
                    version=ver,
                    template=vdata["template"],
                    variables=vdata.get("variables", []),
                    description=vdata.get("description", ""),
                    parent=vdata.get("parent"),
                    created_at=vdata.get("created_at", ""),
                    metadata=vdata.get("metadata", {}),
                )

    def stats(self) -> dict:
        total = sum(len(v) for v in self._templates.values())
        return {"total_templates": len(self._templates), "total_versions": total}


# ── 预置Prompt模板 ────────────────────────────────

DEFAULT_PROMPTS = {
    "agent_system": PromptTemplate(
        name="agent_system",
        version="1.0.0",
        template="""你是一个专业的AI助手，运行在 AgentOS v0.30 上。
你的任务：{{task}}
可用工具：{{tools}}
当前上下文：{{context}}

请逐步思考并执行。输出格式：
1. 思考(thinking)
2. 工具调用(如果需要)
3. 最终回答""",
        variables=["task", "tools", "context"],
        description="Agent核心系统提示",
    ),
    "code_review": PromptTemplate(
        name="code_review",
        version="1.0.0",
        template="""审查以下代码。检查维度：{{dimensions}}

代码：
```
{{code}}
```

输出结构化报告。""",
        variables=["code", "dimensions"],
        description="代码审查Prompt",
    ),
    "research_deep": PromptTemplate(
        name="research_deep",
        version="1.0.0",
        template="""对以下主题进行深度调研：{{topic}}

要求：
1. 多角度分析（至少3个视角）
2. 引用权威来源
3. 对比不同观点
4. 给出可操作的结论

调研深度：{{depth}}""",
        variables=["topic", "depth"],
        description="深度调研Prompt",
    ),
    "summarize": PromptTemplate(
        name="summarize",
        version="1.0.0",
        template="""总结以下内容。摘要长度：{{length}}

内容：
{{content}}

输出格式：{{format}}""",
        variables=["content", "length", "format"],
        description="文档摘要Prompt",
    ),
    "creative_writing": PromptTemplate(
        name="creative_writing",
        version="1.0.0",
        template="""创作一篇{{genre}}，主题：{{topic}}
风格：{{style}}
字数：{{words}}

要求：
1. 开头引人入胜
2. 结构清晰
3. 结尾有力""",
        variables=["genre", "topic", "style", "words"],
        description="创意写作Prompt",
    ),
}
