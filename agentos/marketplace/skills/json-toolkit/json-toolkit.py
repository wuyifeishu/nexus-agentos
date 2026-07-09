"""
json-toolkit — JSON 解析、查询、格式化工具。

Category: data
"""


def run(
    action: str,
    file_path: str = "",
    json_str: str = "",
    query: str = "",
    output_path: str = "",
    indent: int = 2,
) -> str:
    """JSON 操作工具。action: parse/query/format/validate。query 用点号路径如 'users.0.name'。"""
    import json
    import os

    def _load():
        if file_path and os.path.isfile(file_path):
            with open(file_path, encoding="utf-8") as f:
                return json.load(f)
        if json_str:
            return json.loads(json_str)
        return None

    def _query_path(obj, path):
        for key in path.split("."):
            if obj is None:
                return None
            if isinstance(obj, list):
                try:
                    obj = obj[int(key)]
                except (ValueError, IndexError):
                    return None
            elif isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return None
        return obj

    try:
        if action == "validate":
            data = _load()
            if data is None:
                return "[json-toolkit] 无有效输入"
            return f"有效 JSON。类型: {type(data).__name__}"
        if action == "format":
            data = _load()
            if data is None:
                return "[json-toolkit] 无有效输入"
            formatted = json.dumps(data, ensure_ascii=False, indent=indent)
            if output_path:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(formatted)
                return f"已格式化写入: {output_path}"
            return formatted
        if action == "query":
            data = _load()
            if data is None:
                return "[json-toolkit] 无有效输入"
            if not query:
                return "[json-toolkit] query 不能为空"
            result = _query_path(data, query)
            if result is None:
                return f"[json-toolkit] 路径 '{query}' 无匹配"
            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False, indent=indent)
            return str(result)
        if action == "parse":
            data = _load()
            if data is None:
                return "[json-toolkit] 无有效输入"
            if isinstance(data, dict):
                keys = list(data.keys())
                return f"JSON 对象, {len(keys)} 个顶层键: {', '.join(keys[:30])}"
            if isinstance(data, list):
                return f"JSON 数组, {len(data)} 个元素"
            return f"JSON 值: {data}"
        return f"[json-toolkit] 未知操作: {action}, 支持: parse/query/format/validate"
    except json.JSONDecodeError as e:
        return f"[json-toolkit] JSON 解析错误: {e}"
    except Exception as e:
        return f"[json-toolkit] 失败: {e}"


__all__ = ["run"]
