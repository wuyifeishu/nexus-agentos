"""v0.80 — 从模块源码自动生成 Markdown API 文档。"""

from __future__ import annotations

import ast
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DocConfig:
    """文档生成配置。"""

    output_dir: str = "docs/api"
    include_private: bool = False
    include_dunders: bool = False
    max_signature_width: int = 88


@dataclass
class _ClassDoc:
    name: str
    qualname: str
    doc: str
    methods: list[_FuncDoc] = field(default_factory=list)
    base_classes: list[str] = field(default_factory=list)


@dataclass
class _FuncDoc:
    name: str
    qualname: str
    doc: str
    signature: str
    is_async: bool = False
    is_static: bool = False
    is_classmethod: bool = False


@dataclass
class _ModuleDoc:
    name: str
    path: str
    doc: str
    classes: list[_ClassDoc] = field(default_factory=list)
    functions: list[_FuncDoc] = field(default_factory=list)
    submodules: list[str] = field(default_factory=list)


def _parse_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    args = []
    for arg in node.args.args:
        name = arg.arg
        annotation = ast.unparse(arg.annotation) if arg.annotation else ""
        args.append(f"{name}: {annotation}" if annotation else name)
    if node.args.vararg:
        args.append(f"*{node.args.vararg.arg}")
    if node.args.kwarg:
        args.append(f"**{node.args.kwarg.arg}")
    returns = ast.unparse(node.returns) if node.returns else "None"
    prefix = "async " if isinstance(node, ast.AsyncFunctionDef) else ""
    return f"{prefix}def ({', '.join(args)}) -> {returns}"


def _get_docstring(node: ast.AST) -> str:
    doc = ast.get_docstring(node)
    return doc.strip() if doc else ""


class DocGenerator:
    """从 Python 包源码生成 Markdown API 文档。"""

    def __init__(self, config: DocConfig | None = None):
        self.config = config or DocConfig()

    def generate(self, package_path: str) -> str:
        """扫描包目录，生成完整 Markdown 文档。"""
        package_path = os.path.abspath(package_path)
        modules = self._scan(package_path)
        return self._render(modules, package_path)

    def _scan(self, root: str) -> list[_ModuleDoc]:
        results: list[_ModuleDoc] = []
        for dirpath, _, filenames in os.walk(root):
            for fn in sorted(filenames):
                if not fn.endswith(".py") or fn.startswith("_"):
                    continue
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                mod_name = rel[:-3].replace(os.sep, ".")

                try:
                    with open(full) as f:
                        source = f.read()
                    tree = ast.parse(source)
                    doc = _get_docstring(tree)
                    classes, funcs = self._extract_top_level(tree, mod_name)
                    sub = self._find_submodules(tree, mod_name)
                    results.append(
                        _ModuleDoc(
                            name=mod_name,
                            path=rel,
                            doc=doc,
                            classes=classes,
                            functions=funcs,
                            submodules=sub,
                        )
                    )
                except Exception:
                    pass
        return results

    def _extract_top_level(
        self, tree: ast.Module, mod_name: str
    ) -> tuple[list[_ClassDoc], list[_FuncDoc]]:
        classes: list[_ClassDoc] = []
        funcs: list[_FuncDoc] = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                if not self.config.include_private and node.name.startswith("_"):
                    continue
                cd = _ClassDoc(
                    name=node.name,
                    qualname=f"{mod_name}.{node.name}",
                    doc=_get_docstring(node),
                    base_classes=[ast.unparse(b) for b in node.bases],
                )
                for body in node.body:
                    if isinstance(body, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if (
                            not self.config.include_private
                            and body.name.startswith("_")
                            and not body.name.startswith("__")
                        ):
                            continue
                        if body.name.startswith("__") and not self.config.include_dunders:
                            if body.name not in ("__init__", "__str__", "__repr__", "__call__"):
                                continue
                        cd.methods.append(
                            _FuncDoc(
                                name=body.name,
                                qualname=f"{mod_name}.{node.name}.{body.name}",
                                doc=_get_docstring(body),
                                signature=_parse_signature(body),
                                is_async=isinstance(body, ast.AsyncFunctionDef),
                                is_static=any(
                                    isinstance(d, ast.Name) and d.id == "staticmethod"
                                    for d in body.decorator_list
                                ),
                                is_classmethod=any(
                                    isinstance(d, ast.Name) and d.id == "classmethod"
                                    for d in body.decorator_list
                                ),
                            )
                        )
                classes.append(cd)

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not self.config.include_private and node.name.startswith("_"):
                    continue
                funcs.append(
                    _FuncDoc(
                        name=node.name,
                        qualname=f"{mod_name}.{node.name}",
                        doc=_get_docstring(node),
                        signature=_parse_signature(node),
                        is_async=isinstance(node, ast.AsyncFunctionDef),
                    )
                )

        return classes, funcs

    @staticmethod
    def _find_submodules(tree: ast.Module, mod_name: str) -> list[str]:
        subs = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name.startswith("agentos."):
                        subs.append(alias.name)
        return sorted(set(subs))

    def _render(self, modules: list[_ModuleDoc], root: str) -> str:
        lines = [
            "# AgentOS API Reference",
            "",
            f"> 自动生成 | 版本 {self._get_version(root)} | {len(modules)} 个模块",
            "",
            "---",
            "",
            "## 目录",
            "",
        ]
        for m in modules:
            lines.append(f"- [{m.name}](#{m.name.replace('.', '')})")
        lines.extend(["", "---", ""])

        for m in modules:
            lines.append(f"## {m.name}")
            lines.append("")
            if m.doc:
                lines.append(m.doc)
                lines.append("")

            if m.classes:
                lines.append("### 类")
                lines.append("")
                for c in m.classes:
                    bases = f"({', '.join(c.base_classes)})" if c.base_classes else ""
                    lines.append(f"#### `{c.name}{bases}`")
                    lines.append("")
                    if c.doc:
                        lines.append(c.doc)
                        lines.append("")
                    if c.methods:
                        lines.append("| 方法 | 签名 |")
                        lines.append("|------|------|")
                        for meth in c.methods:
                            sig = meth.signature[: self.config.max_signature_width]
                            prefix = ""
                            if meth.is_classmethod:
                                prefix = "@classmethod "
                            elif meth.is_static:
                                prefix = "@staticmethod "
                            lines.append(f"| `{prefix}{meth.name}` | `{sig}` |")
                        lines.append("")

            if m.functions:
                lines.append("### 函数")
                lines.append("")
                lines.append("| 函数 | 签名 |")
                lines.append("|------|------|")
                for f in m.functions:
                    sig = f.signature[: self.config.max_signature_width]
                    prefix = "async " if f.is_async else ""
                    lines.append(f"| `{prefix}{f.name}` | `{sig}` |")
                lines.append("")

            if m.submodules:
                lines.append("**导入子模块:** " + ", ".join(f"`{s}`" for s in m.submodules))
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _get_version(root: str) -> str:
        try:
            sys.path.insert(0, os.path.dirname(root))
            import agentos

            return getattr(agentos, "__version__", "?.?.?")
        except Exception:
            return "?.?.?"


def generate_api_docs(package_path: str, output_path: str | None = None) -> str:
    """便捷函数：生成 API 文档到文件。"""
    gen = DocGenerator()
    md = gen.generate(package_path)
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            f.write(md)
    return md


def generate_quickstart(output_path: str) -> str:
    """生成 Quick Start 模板。"""
    content = """\
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
"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write(content)
    return content
