"""
markdown-toolkit — Markdown 处理工具：转 HTML、提取标题、生成目录。

Category: utility
"""


def run(action: str, file_path: str = "", text: str = "", output_path: str = "") -> str:
    """Markdown 处理工具。action: toc/to_html/headings/stats。"""
    import os
    import re

    def _read():
        if file_path and os.path.isfile(file_path):
            with open(file_path, encoding="utf-8") as f:
                return f.read()
        return text or ""

    content = _read()
    if not content:
        return "[markdown-toolkit] 无内容输入"

    try:
        if action == "stats":
            lines = content.split("\n")
            words = len(content.split())
            chars = len(content)
            headings = len(re.findall(r"^#{1,6}\s", content, re.MULTILINE))
            links = len(re.findall(r"\[.*?\]\(.*?\)", content))
            code_blocks = len(re.findall(r"```", content)) // 2
            return f"行数: {len(lines)}, 词数: {words}, 字符: {chars}, 标题: {headings}, 链接: {links}, 代码块: {code_blocks}"  # noqa: E501

        if action == "headings":
            matches = re.findall(r"^(#{1,6})\s+(.+)$", content, re.MULTILINE)
            if not matches:
                return "[markdown-toolkit] 未找到标题"
            lines_out = []
            for level, title in matches:
                indent = "  " * (len(level) - 1)
                lines_out.append(f"{indent}- {title.strip()}")
            return f"共 {len(matches)} 个标题:\n" + "\n".join(lines_out)

        if action == "toc":
            matches = re.findall(r"^(#{1,6})\s+(.+)$", content, re.MULTILINE)
            if not matches:
                return "[markdown-toolkit] 未找到标题"
            lines_out = ["# 目录", ""]
            for level, title in matches:
                depth = len(level)
                indent = "  " * (depth - 1)
                anchor = re.sub(r"[^\w\s-]", "", title.strip()).lower().replace(" ", "-")
                lines_out.append(f"{indent}- [{title.strip()}](#{anchor})")
            return "\n".join(lines_out)

        if action == "to_html":
            # Simple markdown-to-HTML converter (covers basics)
            html = content
            # Code blocks (```)
            html = re.sub(
                r"```(\w*)\n(.*?)```",
                r"<pre><code class='\1'>\2</code></pre>",
                html,
                flags=re.DOTALL,
            )
            # Inline code
            html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)
            # Headings
            for i in range(6, 0, -1):
                html = re.sub(rf"^{'#'*i}\s+(.+)$", rf"<h{i}>\1</h{i}>", html, flags=re.MULTILINE)
            # Bold/Italic
            html = re.sub(r"\*\*\*(.+?)\*\*\*", r"<em><strong>\1</strong></em>", html)
            html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
            html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
            # Links
            html = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', html)
            # Images
            html = re.sub(r"!\[(.*?)\]\((.+?)\)", r'<img src="\2" alt="\1">', html)
            # Unordered lists
            html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
            # Paragraphs (double newline)
            html = re.sub(r"\n\n+", "</p><p>", html)
            html = f"<p>{html}</p>"
            if output_path:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(html)
                return f"已转换并写入: {output_path}"
            # return first 2000 chars if too long
            if len(html) > 2000:
                return html[:2000] + f"\n... (共{len(html)}字符)"
            return html

        return f"[markdown-toolkit] 未知操作: {action}, 支持: toc/to_html/headings/stats"
    except Exception as e:
        return f"[markdown-toolkit] 失败: {e}"


__all__ = ["run"]
