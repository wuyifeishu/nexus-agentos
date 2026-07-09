"""
csv-toolkit — CSV 处理工具集：读取、过滤、统计、导出。

Category: data
"""


def run(
    action: str,
    file_path: str = "",
    query: str = "",
    output_path: str = "",
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> str:
    """CSV 文件操作工具。action: headers/read/stats/filter。filter 时 query 格式 'col op value'。"""
    import csv
    import os

    if not file_path or not os.path.isfile(file_path):
        return f"[csv-toolkit] 文件不存在: {file_path}"
    try:
        with open(file_path, encoding=encoding, newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            if reader.fieldnames is None:
                return "[csv-toolkit] 无法解析表头"
            headers = list(reader.fieldnames)
            rows = list(reader)
        if action == "headers":
            return f"表头({len(headers)}列): {', '.join(headers)}\n行数: {len(rows)}"
        if action == "read":
            preview = rows[:20]
            lines = [delimiter.join(headers)]
            for row in preview:
                lines.append(delimiter.join(str(row.get(h, "")) for h in headers))
            tail = f"\n... (共{len(rows)}行,显示前{len(preview)}行)" if len(rows) > 20 else ""
            return "\n".join(lines) + tail
        if action == "stats":
            res = [f"文件: {file_path}", f"行数: {len(rows)}", f"列数: {len(headers)}"]
            for h in headers:
                vals = [row.get(h, "") for row in rows]
                ne = sum(1 for v in vals if v.strip())
                try:
                    nums = [float(v) for v in vals if v.strip()]
                    if nums:
                        res.append(
                            f"  {h}: 非空={ne}, 数值={len(nums)}, min={min(nums):.2f}, max={max(nums):.2f}, avg={sum(nums)/len(nums):.2f}"  # noqa: E501
                        )
                    else:
                        res.append(f"  {h}: 非空={ne}")
                except ValueError:
                    res.append(f"  {h}: 非空={ne}")
            return "\n".join(res)
        if action == "filter":
            if not query:
                return "[csv-toolkit] filter 需要 query='col op value'"
            parts = query.split(maxsplit=2)
            if len(parts) < 3:
                return "[csv-toolkit] query格式: 'col op value'"
            col, op, val = parts[0], parts[1], parts[2]
            if col not in headers:
                return f"[csv-toolkit] 列'{col}'不存在,可用: {', '.join(headers)}"
            filtered = []
            for row in rows:
                cell = row.get(col, "")
                try:
                    if op == ">":
                        m = float(cell) > float(val)
                    elif op == "<":
                        m = float(cell) < float(val)
                    elif op == ">=":
                        m = float(cell) >= float(val)
                    elif op == "<=":
                        m = float(cell) <= float(val)
                    elif op == "==":
                        m = str(cell).strip() == val.strip()
                    elif op == "!=":
                        m = str(cell).strip() != val.strip()
                    elif op == "contains":
                        m = val.strip().lower() in str(cell).lower()
                    else:
                        return f"[csv-toolkit] 不支持操作符: {op}"
                except ValueError:
                    m = False
                if m:
                    filtered.append(row)
            s = f"过滤: {col} {op} {val}\n匹配: {len(filtered)}/{len(rows)}"
            if output_path and filtered:
                with open(output_path, "w", encoding=encoding, newline="") as f:
                    w = csv.DictWriter(f, fieldnames=headers)
                    w.writeheader()
                    w.writerows(filtered)
                s += f"\n已写入: {output_path}"
            elif filtered:
                lines = [delimiter.join(headers)]
                for row in filtered[:10]:
                    lines.append(delimiter.join(str(row.get(h, "")) for h in headers))
                s += "\n" + ("\n".join(lines))
            return s
        return f"[csv-toolkit] 未知操作: {action}, 支持: headers/read/stats/filter"
    except Exception as e:
        return f"[csv-toolkit] 失败: {e}"


__all__ = ["run"]
