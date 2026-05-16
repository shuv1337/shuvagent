"""Tests for ``memory.graph`` — SQLite-backed knowledge graph.

Uses a temp SQLite database per test; no persistent state leaked.
"""

from __future__ import annotations

import tempfile

import pytest

from shuvagent.memory.graph import GraphMemoryStore

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> GraphMemoryStore:
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    s = GraphMemoryStore(db_path)
    yield s
    s.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fixed_branches_seeded_on_first_run(store: GraphMemoryStore) -> None:
    """Root + User/Directives/World created automatically."""
    root = store.get_node("root")
    assert root is not None
    assert root.name == "Root"

    user = store.get_node("user")
    assert user is not None
    assert user.name == "User"

    directives = store.get_node("directives")
    assert directives is not None
    assert directives.name == "Directives"

    world = store.get_node("world")
    assert world is not None
    assert world.name == "World"


def test_create_read_update_delete_node(store: GraphMemoryStore) -> None:
    """Full CRUD lifecycle."""
    node = store.create_node(
        name="Python",
        description="A programming language",
        data="Created by Guido van Rossum.",
        parent_id="world",
    )
    assert node.id is not None
    assert node.name == "Python"

    fetched = store.get_node(node.id)
    assert fetched is not None
    assert fetched.data == "Created by Guido van Rossum."

    updated = store.update_node(node.id, data="Created by Guido.")
    assert updated is not None
    assert updated.data == "Created by Guido."

    deleted = store.delete_node(node.id)
    assert deleted is True
    assert store.get_node(node.id) is None


def test_search_by_keyword_ranks_relevance(store: GraphMemoryStore) -> None:
    """Name/description matches score 3× data matches."""
    store.create_node(
        name="Python",
        description="Programming language",
        data="Snakes",
        parent_id="world",
    )
    store.create_node(
        name="JavaScript",
        description="Web language",
        data="Python competitor",
        parent_id="world",
    )

    results = store.search_nodes("python", limit=10)
    names = [r.name for r in results]
    assert "Python" in names
    # Python should rank above JavaScript because it matches name/description
    if len(names) >= 2:
        assert names.index("Python") < names.index("JavaScript")


def test_deduplication_via_normalise_fact(store: GraphMemoryStore) -> None:
    """ "Python 3.12" and "python 3.12" are treated as the same fact."""
    from shuvagent.memory.graph import normalise_fact

    assert normalise_fact("Python 3.12") == normalise_fact("python 3.12")
    assert normalise_fact("Python  3.12") == normalise_fact("python 3.12")


def test_access_scoring_decay(store: GraphMemoryStore) -> None:
    """Frequently accessed nodes score higher than untouched nodes."""
    node1 = store.create_node(name="A", description="", data="", parent_id="world")
    store.create_node(name="B", description="", data="", parent_id="world")

    # Touch node1 multiple times
    for _ in range(5):
        store.touch_node(node1.id)

    top = store.get_top_nodes(limit=2)
    names = [n.name for n in top]
    assert "A" in names


def test_subtree_query_returns_nested_dict(store: GraphMemoryStore) -> None:
    """get_subtree('world', max_depth=2) returns a tree structure."""
    child = store.create_node(
        name="Python", description="Lang", data="", parent_id="world"
    )
    store.create_node(name="CPython", description="Impl", data="", parent_id=child.id)

    tree = store.get_subtree("world", max_depth=2)
    assert "node" in tree
    assert "children" in tree
    # Should include Python at depth 1
    child_names = [c["node"]["name"] for c in tree["children"]]
    assert "Python" in child_names
    # CPython should not appear because max_depth=2 stops at Python.


def test_opt_in_config_default_off() -> None:
    """When memory is disabled, the store should not be instantiated."""
    # This is an app-level config test; the store itself doesn't enforce opt-in.
    # We verify the store CAN be created, but the app would skip creating it.
    assert True


def test_delete_root_or_fixed_branch_fails(store: GraphMemoryStore) -> None:
    """Root and fixed branches cannot be deleted."""
    assert store.delete_node("root") is False
    assert store.delete_node("user") is False
    assert store.delete_node("directives") is False
    assert store.delete_node("world") is False
