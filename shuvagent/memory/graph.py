"""Knowledge graph memory store backed by SQLite.

Self-organising node graph with three fixed top-level branches:
  - user:       identity, preferences, plans
  - directives: behaviour rules issued by the user
  - world:      external facts learned from conversations
"""

from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4


@dataclass
class MemoryNode:
    """A single node in the memory graph."""

    id: str
    name: str
    description: str
    data: str = ""
    parent_id: str | None = None
    access_count: int = 0
    last_accessed: str = ""
    created_at: str = ""
    updated_at: str = ""
    data_token_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "data": self.data,
            "parent_id": self.parent_id,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "data_token_count": self.data_token_count,
        }


class GraphMemoryStore:
    """SQLite-backed graph memory store."""

    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS memory_nodes (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT NOT NULL,
              data TEXT NOT NULL,
              parent_id TEXT,
              access_count INTEGER NOT NULL,
              last_accessed TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              data_token_count INTEGER NOT NULL
            )
            """
        )
        self._seed_fixed_branches()

    def create_node(
        self,
        name: str,
        description: str,
        data: str = "",
        parent_id: str | None = None,
    ) -> MemoryNode:
        now = _now()
        node = MemoryNode(
            id=str(uuid4()),
            name=name,
            description=description,
            data=data,
            parent_id=parent_id,
            created_at=now,
            updated_at=now,
            data_token_count=_estimate_tokens(data),
        )
        self._insert(node)
        return node

    def get_node(self, node_id: str) -> MemoryNode | None:
        row = self._conn.execute(
            "SELECT * FROM memory_nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return _node_from_row(row) if row is not None else None

    def update_node(self, node_id: str, **kwargs: Any) -> MemoryNode | None:
        node = self.get_node(node_id)
        if node is None:
            return None
        allowed = {
            "name",
            "description",
            "data",
            "parent_id",
            "access_count",
            "last_accessed",
        }
        updates = {key: value for key, value in kwargs.items() if key in allowed}
        if not updates:
            return node
        updates["updated_at"] = _now()
        if "data" in updates:
            updates["data_token_count"] = _estimate_tokens(str(updates["data"]))
        assignments = ", ".join(f"{key} = ?" for key in updates)
        self._conn.execute(
            f"UPDATE memory_nodes SET {assignments} WHERE id = ?",
            (*updates.values(), node_id),
        )
        self._conn.commit()
        return self.get_node(node_id)

    def delete_node(self, node_id: str) -> bool:
        if node_id in {"root", "user", "directives", "world"}:
            return False
        result = self._conn.execute("DELETE FROM memory_nodes WHERE id = ?", (node_id,))
        self._conn.commit()
        return result.rowcount > 0

    def search_nodes(self, query: str, limit: int = 10) -> list[MemoryNode]:
        query_norm = normalise_fact(query)
        scored: list[tuple[int, MemoryNode]] = []
        for node in self.get_all_nodes():
            score = 0
            if query_norm in normalise_fact(node.name):
                score += 3
            if query_norm in normalise_fact(node.description):
                score += 3
            if query_norm in normalise_fact(node.data):
                score += 1
            if score:
                scored.append((score, node))
        return [
            node
            for _, node in sorted(scored, key=lambda item: (-item[0], item[1].name))[
                :limit
            ]
        ]

    def get_children(self, node_id: str) -> list[MemoryNode]:
        rows = self._conn.execute(
            "SELECT * FROM memory_nodes WHERE parent_id = ? ORDER BY name", (node_id,)
        ).fetchall()
        return [_node_from_row(row) for row in rows]

    def get_subtree(self, node_id: str, max_depth: int = 3) -> dict[str, Any]:
        node = self.get_node(node_id)
        if node is None:
            return {}

        def build(current: MemoryNode, depth: int) -> dict[str, Any]:
            children = []
            if depth + 1 < max_depth:
                children = [
                    build(child, depth + 1) for child in self.get_children(current.id)
                ]
            return {"node": current.to_dict(), "children": children}

        return build(node, 0)

    def get_all_nodes(self) -> list[MemoryNode]:
        rows = self._conn.execute("SELECT * FROM memory_nodes ORDER BY name").fetchall()
        return [_node_from_row(row) for row in rows]

    def touch_node(self, node_id: str) -> None:
        self._conn.execute(
            """
            UPDATE memory_nodes
            SET access_count = access_count + 1, last_accessed = ?, updated_at = ?
            WHERE id = ?
            """,
            (_now(), _now(), node_id),
        )
        self._conn.commit()

    def get_top_nodes(self, limit: int = 10) -> list[MemoryNode]:
        rows = self._conn.execute(
            """
            SELECT * FROM memory_nodes
            ORDER BY access_count DESC, last_accessed DESC, name ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_node_from_row(row) for row in rows]

    def close(self) -> None:
        self._conn.close()

    def _insert(self, node: MemoryNode) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO memory_nodes (
              id, name, description, data, parent_id, access_count,
              last_accessed, created_at, updated_at, data_token_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node.id,
                node.name,
                node.description,
                node.data,
                node.parent_id,
                node.access_count,
                node.last_accessed,
                node.created_at,
                node.updated_at,
                node.data_token_count,
            ),
        )
        self._conn.commit()

    def _seed_fixed_branches(self) -> None:
        now = _now()
        for node in [
            MemoryNode(
                "root", "Root", "Memory graph root", created_at=now, updated_at=now
            ),
            MemoryNode(
                "user",
                "User",
                "User facts",
                parent_id="root",
                created_at=now,
                updated_at=now,
            ),
            MemoryNode(
                "directives",
                "Directives",
                "User directives and preferences",
                parent_id="root",
                created_at=now,
                updated_at=now,
            ),
            MemoryNode(
                "world",
                "World",
                "World facts",
                parent_id="root",
                created_at=now,
                updated_at=now,
            ),
        ]:
            self._insert(node)


def normalise_fact(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _estimate_tokens(value: str) -> int:
    return max(0, len(value.split()))


def _node_from_row(row: sqlite3.Row) -> MemoryNode:
    return MemoryNode(
        id=str(row["id"]),
        name=str(row["name"]),
        description=str(row["description"]),
        data=str(row["data"]),
        parent_id=row["parent_id"],
        access_count=int(row["access_count"]),
        last_accessed=str(row["last_accessed"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        data_token_count=int(row["data_token_count"]),
    )

    def get_node_count(self) -> int:
        raise NotImplementedError("GraphMemoryStore not yet implemented")

    def close(self) -> None:
        raise NotImplementedError("GraphMemoryStore not yet implemented")
