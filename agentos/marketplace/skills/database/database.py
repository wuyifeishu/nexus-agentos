"""
database — Local SQLite database operations.

Actions: query, tables, schema, create_table, insert
Works with any .db/.sqlite file. :memory: in same process shares one connection.
"""

import sqlite3
from typing import Any

# Persist :memory: connections within same process
_mem_conn = None


def _get_conn(db_path: str):
    global _mem_conn
    if db_path == ":memory:":
        if _mem_conn is None:
            _mem_conn = sqlite3.connect(":memory:")
            _mem_conn.row_factory = sqlite3.Row
        return _mem_conn
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def run(action: str = "tables", db_path: str = ":memory:", query: str = "", **kwargs: Any) -> str:
    try:
        conn = _get_conn(db_path)
    except Exception as e:
        return f"[database] Connection error: {e}"

    try:
        if action == "tables":
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()
            tables = [r[0] for r in rows]
            return (
                f"Tables ({len(tables)}): " + ", ".join(tables)
                if tables
                else "[database] No tables."
            )

        if action == "schema":
            if not query:
                return "[database] Table name required for schema."
            rows = conn.execute(f"PRAGMA table_info({query})").fetchall()
            cols = [f"{r['name']} {r['type']}" for r in rows]
            return f"Schema for {query}:\n" + "\n".join(f"  {c}" for c in cols)

        if action == "query":
            if not query:
                return "[database] SQL query required."
            cur = conn.execute(query)
            rows = cur.fetchall()
            if cur.description:
                headers = [d[0] for d in cur.description]
                result = "\t".join(headers) + "\n"
                result += "\n".join("\t".join(str(v) for v in row) for row in rows[:50])
                return result
            return f"Query executed. Affected rows: {cur.rowcount}"

        if action == "create_table":
            if not query:
                return "[database] CREATE TABLE statement required."
            conn.execute(query)
            conn.commit()
            return "[database] Table created."

        if action == "insert":
            if not query:
                return "[database] INSERT statement required."
            conn.execute(query)
            conn.commit()
            return f"[database] Row inserted. Last ID: {conn.execute('SELECT last_insert_rowid()').fetchone()[0]}"

        return f"[database] Unknown action: {action}"

    except Exception as e:
        return f"[database] Error: {e}"
    finally:
        if db_path != ":memory:":
            conn.close()


__all__ = ["run"]
