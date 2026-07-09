"""
data-analysis — 基本数据分析：描述性统计、相关性、频率分布。

Category: data
"""


def run(
    action: str,
    file_path: str = "",
    column: str = "",
    group_by: str = "",
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> str:
    """数据分析工具。action: describe/correlation/freq/top_n。输入为 CSV 文件。"""
    import collections
    import csv
    import math
    import os

    if not file_path or not os.path.isfile(file_path):
        return f"[data-analysis] 文件不存在: {file_path}"

    try:
        with open(file_path, encoding=encoding, newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            if reader.fieldnames is None:
                return "[data-analysis] 无法解析表头"
            headers = list(reader.fieldnames)
            rows = list(reader)

        def _numeric(col):
            vals = []
            for row in rows:
                v = row.get(col, "")
                try:
                    vals.append(float(v))
                except ValueError:
                    pass
            return vals

        if action == "describe":
            target = [column] if column and column in headers else headers
            result = [f"文件: {file_path}", f"行数: {len(rows)}", ""]
            for col in target:
                vals = _numeric(col)
                if not vals:
                    result.append(f"{col}: 无数值数据")
                    continue
                n = len(vals)
                mean = sum(vals) / n
                srt = sorted(vals)
                median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
                var = sum((x - mean) ** 2 for x in vals) / n
                std = math.sqrt(var)
                result.append(
                    f"{col}: count={n}, mean={mean:.4f}, std={std:.4f}, "
                    f"min={min(vals):.4f}, 25%={srt[n//4]:.4f}, median={median:.4f}, "
                    f"75%={srt[3*n//4]:.4f}, max={max(vals):.4f}"
                )
            return "\n".join(result)

        if action == "correlation":
            numeric_cols = [h for h in headers if _numeric(h)]
            if len(numeric_cols) < 2:
                return "[data-analysis] 需要至少 2 个数值列"
            if column:
                targets = [column] if column in numeric_cols else numeric_cols[:2]
            else:
                targets = numeric_cols[: min(5, len(numeric_cols))]

            def _pearson(xs, ys):
                n = min(len(xs), len(ys))
                mx, my = sum(xs) / n, sum(ys) / n
                num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
                dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
                dy = math.sqrt(sum((y - my) ** 2 for y in ys))
                return num / (dx * dy) if dx and dy else 0

            result = ["相关性矩阵:", ""]
            result.append("         " + "  ".join(f"{t:>8}" for t in targets))
            for t1 in targets:
                row_vals = [f"{t1:<8}"]
                vals1 = _numeric(t1)
                for t2 in targets:
                    if t1 == t2:
                        row_vals.append(f"{1.0:>8.3f}")
                    elif t1 < t2:
                        row_vals.append(f"{_pearson(vals1,_numeric(t2)):>8.3f}")
                    else:
                        row_vals.append("        ")
                result.append("  ".join(row_vals))
            return "\n".join(result)

        if action == "freq":
            if not column or column not in headers:
                return f"[data-analysis] 请指定有效列名。可用: {', '.join(headers)}"
            counter = collections.Counter(row.get(column, "") for row in rows)
            lines = [f"{column} 频率分布 (共{len(counter)}个不同值):"]
            for val, cnt in counter.most_common(20):
                pct = cnt / len(rows) * 100
                lines.append(f"  {val}: {cnt} ({pct:.1f}%)")
            return "\n".join(lines)

        if action == "top_n":
            if not column or column not in headers:
                return f"[data-analysis] 请指定有效列名。可用: {', '.join(headers)}"
            vals = []
            for row in rows:
                v = row.get(column, "")
                try:
                    vals.append((float(v), row))
                except ValueError:
                    pass
            vals.sort(key=lambda x: x[0], reverse=True)
            lines = [f"{column} Top 10:"]
            for i, (val, row) in enumerate(vals[:10]):
                lines.append(f"  {i+1}. {column}={val}  |  {dict(row)}")
            return "\n".join(lines)

        return f"[data-analysis] 未知操作: {action}, 支持: describe/correlation/freq/top_n"
    except Exception as e:
        return f"[data-analysis] 失败: {e}"


__all__ = ["run"]
