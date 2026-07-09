"""
code-review — Static code analysis and review.

Actions: complexity, functions, imports, todo_fixme, lines
"""

import re
from pathlib import Path
from typing import Any


def run(action: str = "overview", file_path: str = "", code: str = "", **kwargs: Any) -> str:
    content = code
    if file_path:
        try:
            content = Path(file_path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"[code-review] File not found: {file_path}"
        except Exception as e:
            return f"[code-review] Error: {e}"

    if not content.strip():
        return "[code-review] No code provided."

    lines = content.split("\n")

    if action == "lines":
        total = len(lines)
        code_lines = len([ln for ln in lines if ln.strip() and not ln.strip().startswith("#")])
        comment_lines = len([ln for ln in lines if ln.strip().startswith("#")])
        blank_lines = len([ln for ln in lines if not ln.strip()])
        return (
            f"Total: {total}, Code: {code_lines}, Comments: {comment_lines}, Blank: {blank_lines}"
        )

    if action == "functions":
        funcs = re.findall(r"^\s*(?:def|async def)\s+(\w+)", content, re.MULTILINE)
        classes = re.findall(r"^\s*class\s+(\w+)", content, re.MULTILINE)
        result = f"Functions ({len(funcs)}): {', '.join(funcs[:20])}\n"
        result += f"Classes ({len(classes)}): {', '.join(classes[:10])}"
        return result

    if action == "imports":
        imports = re.findall(r"^(?:import\s+(\S+)|from\s+(\S+)\s+import)", content, re.MULTILINE)
        deps = set()
        for m in imports:
            deps.add(m[0] or m[1])
        return f"Imports ({len(deps)}): {', '.join(sorted(deps))}"

    if action == "todo_fixme":
        todos = re.findall(r".*?(TODO|FIXME|HACK|XXX)[: ]*(.*)", content)
        if not todos:
            return "[code-review] No TODOs found."
        return "TODOs/FIXMEs:\n" + "\n".join(
            f"  L{content[:content.index(t[1])].count(chr(10))+1}: {t[0]}: {t[1].strip()}"
            for t in todos
        )

    if action == "complexity":
        func_pattern = re.compile(r"^\s*(?:def|async def)\s+(\w+)", re.MULTILINE)
        funcs = {}
        current_func = None
        for i, line in enumerate(lines):
            m = func_pattern.match(line)
            if m:
                current_func = m.group(1)
                funcs[current_func] = {"start": i, "lines": 0, "branches": 0}
            elif current_func:
                funcs[current_func]["lines"] += 1
                if re.search(r"\b(if|elif|for|while|except|and|or)\b", line):
                    funcs[current_func]["branches"] += 1
        result = []
        for name, f in sorted(funcs.items(), key=lambda x: -x[1]["branches"]):
            score = f["branches"] + 1
            flag = "HIGH" if score > 10 else ("MED" if score > 5 else "LOW")
            result.append(f"  {name}: {f['lines']} lines, complexity ~{score} ({flag})")
        return "Function Complexity:\n" + "\n".join(result[:15])

    # Default: overview
    total = len(lines)
    func_count = len(re.findall(r"^\s*(?:def|async def)\s+", content, re.MULTILINE))
    class_count = len(re.findall(r"^\s*class\s+", content, re.MULTILINE))
    import_count = len(re.findall(r"^(?:import|from\s+\S+\s+import)", content, re.MULTILINE))
    return f"[code-review] {total} lines, {func_count} functions, {class_count} classes, {import_count} imports"


__all__ = ["run"]
