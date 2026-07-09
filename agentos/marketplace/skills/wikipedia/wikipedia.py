"""
wikipedia — Wikipedia 搜索与摘要获取（无需 API Key）。

Category: knowledge
"""


def run(action: str, query: str = "", lang: str = "zh") -> str:
    """Wikipedia 查询工具。action: search/summary/page。lang: zh/en/ja 等。"""
    import json
    import urllib.parse
    import urllib.request

    if not query:
        return "[wikipedia] 需要 query 参数"

    base = f"https://{lang}.wikipedia.org/w/api.php"

    try:
        if action == "search":
            params = urllib.parse.urlencode(
                {
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 10,
                }
            )
            url = f"{base}?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "AgentOS/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            results = data.get("query", {}).get("search", [])
            if not results:
                return f"[wikipedia] 未找到 '{query}' 相关条目"
            lines = [f"Wikipedia 搜索结果 ({len(results)} 条):"]
            for i, r in enumerate(results):
                lines.append(f"  {i+1}. {r['title']} - {r.get('snippet','')[:80]}...")
            return "\n".join(lines)

        if action in ("summary", "page"):
            # Get page extract
            params = urllib.parse.urlencode(
                {
                    "action": "query",
                    "prop": "extracts",
                    "exintro": "1",
                    "explaintext": "1",
                    "titles": query,
                    "format": "json",
                    "exchars": "2000" if action == "summary" else "5000",
                }
            )
            url = f"{base}?{params}"
            req = urllib.request.Request(url, headers={"User-Agent": "AgentOS/1.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                if pid == "-1":
                    return f"[wikipedia] 页面 '{query}' 不存在"
                title = page.get("title", "")
                extract = page.get("extract", "")
                if not extract:
                    return f"[wikipedia] 页面 '{title}' 无内容"
                return f"=== {title} ===\n\n{extract}"
            return f"[wikipedia] 未找到 '{query}'"

        return f"[wikipedia] 未知操作: {action}, 支持: search/summary/page"
    except Exception as e:
        return f"[wikipedia] 查询失败: {e}"


__all__ = ["run"]
