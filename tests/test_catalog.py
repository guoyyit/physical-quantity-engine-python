import threading

import pytest

from pqengine.catalog import Catalog
from pqengine.errors import EngineError, ErrorCode
from pqengine.quantity import make_quantity
from pqengine.units import default_registry


@pytest.fixture
def reg():
    return default_registry()


def test_initial_empty_version():
    cat = Catalog()
    assert cat.current().version == 0
    assert cat.current().entries == {}
    assert cat.list_versions() == [0]


def test_commit_creates_new_version(reg):
    cat = Catalog()
    v1 = cat.commit({"x": make_quantity(1.0, "m", registry=reg)})
    assert v1.version == 1
    assert cat.current().version == 1
    assert cat.get_version(0).entries == {}
    assert cat.get_version(1).entries["x"].value == 1.0


def test_commit_is_full_snapshot_not_diff(reg):
    cat = Catalog()
    cat.commit({"x": make_quantity(1.0, "m", registry=reg)})
    v2 = cat.commit({"y": make_quantity(2.0, "s", registry=reg)})
    assert "x" not in v2.entries
    assert "y" in v2.entries


def test_optimistic_concurrency_conflict(reg):
    cat = Catalog()
    cat.commit({}, expected_version=0)
    with pytest.raises(EngineError) as exc:
        cat.commit({}, expected_version=0)
    assert exc.value.code == ErrorCode.CATALOG_CONFLICT
    # Failed commit must not create a version.
    assert cat.list_versions() == [0, 1]


def test_missing_version(reg):
    cat = Catalog()
    with pytest.raises(EngineError) as exc:
        cat.get_version(99)
    assert exc.value.code == ErrorCode.VERSION_NOT_FOUND


def test_lookup_known_and_unknown(reg):
    cat = Catalog()
    cat.commit({"x": make_quantity(1.0, "m", registry=reg)})
    assert cat.lookup(1, "x").value == 1.0
    with pytest.raises(EngineError) as exc:
        cat.lookup(1, "missing")
    assert exc.value.code == ErrorCode.UNKNOWN_QUANTITY


def test_concurrent_commits_never_mix(reg):
    cat = Catalog()
    q = make_quantity(1.0, "m", registry=reg)
    observed: list[tuple[int, int]] = []
    stop = threading.Event()

    def committer():
        i = 0
        while not stop.is_set() and i < 50:
            entries = {f"k{j}": q for j in range(20)}
            cat.commit(entries)
            i += 1

    def reader():
        while not stop.is_set():
            snap = cat.current()
            observed.append((snap.version, len(snap.entries)))

    t1 = threading.Thread(target=committer)
    t2 = threading.Thread(target=reader)
    t1.start()
    t2.start()
    t1.join()
    stop.set()
    t2.join()

    # Every observed snapshot is complete: empty (v0) or 20 entries.
    for version, size in observed:
        assert size in (0, 20)
    assert cat.current().version == 50
