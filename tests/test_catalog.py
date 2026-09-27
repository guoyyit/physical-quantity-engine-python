import threading

import pytest

from pqe.errors import EngineError, ErrorCode


def test_initial_empty_version(catalog):
    assert catalog.head_version() == 0
    assert dict(catalog.snapshot().entries) == {}


def test_add_converts_to_base_units(catalog):
    version = catalog.add("x", "1", "km")
    entry = version.get("x")
    assert entry.value == 1000
    assert entry.dimension.format() == "L"


def test_uncertainty_uses_unit_scale(catalog):
    version = catalog.add("t", "100", "km", uncertainty="2")
    assert version.get("t").uncertainty == 2000


def test_versions_are_immutable_history(catalog):
    v1 = catalog.add("x", "1", "m")
    v2 = catalog.add("y", "2", "m")
    assert set(v1.entries) == {"x"}
    assert set(v2.entries) == {"x", "y"}
    with pytest.raises(TypeError):
        v1.entries["z"] = None


def test_unknown_name_and_version(catalog):
    with pytest.raises(EngineError) as exc:
        catalog.snapshot().get("missing")
    assert exc.value.code is ErrorCode.UNKNOWN_NAME
    with pytest.raises(EngineError) as exc:
        catalog.get_version(42)
    assert exc.value.code is ErrorCode.VERSION_NOT_FOUND


def test_stale_base_version_conflicts(catalog):
    catalog.add("x", "1", "m")
    with pytest.raises(EngineError) as exc:
        catalog.add("y", "2", "m", base_version=0)
    assert exc.value.code is ErrorCode.CATALOG_CONFLICT


def test_concurrent_commits_never_mix(catalog):
    def worker(k):
        for j in range(50):
            try:
                catalog.add(f"q{k}_{j}", "1", "m")
            except EngineError as exc:
                assert exc.code is ErrorCode.CATALOG_CONFLICT

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    head = catalog.snapshot()
    # Every published version is a complete superset of its predecessor.
    prev_count = 0
    for v in range(1, head.version + 1):
        snap = catalog.get_version(v)
        assert len(snap.entries) == prev_count + 1
        prev_count += 1
    # No reader ever observes torn state: all names resolve consistently.
    for name in head.entries:
        head.get(name)


def test_concurrent_readers_see_consistent_version(catalog):
    catalog.add("anchor", "1", "m")
    stop = threading.Event()
    errors = []

    def reader():
        while not stop.is_set():
            snap = catalog.snapshot()
            names = list(snap.entries)
            # A snapshot must answer all of its own names.
            for name in names:
                try:
                    snap.get(name)
                except EngineError as exc:
                    errors.append(exc)

    def writer():
        for i in range(100):
            catalog.add(f"w{i}", "1", "m")

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    writer_thread = threading.Thread(target=writer)
    writer_thread.start()
    writer_thread.join()
    stop.set()
    for t in threads:
        t.join()
    assert not errors


def test_invalid_entry_inputs(catalog):
    with pytest.raises(EngineError) as exc:
        catalog.add("1bad", "1", "m")
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT
    with pytest.raises(EngineError) as exc:
        catalog.add("ok", "NaN", "m")
    assert exc.value.code is ErrorCode.NON_FINITE_VALUE
    with pytest.raises(EngineError) as exc:
        catalog.add("ok", "1", "nonsense-unit")
    assert exc.value.code is ErrorCode.UNKNOWN_UNIT
    with pytest.raises(EngineError) as exc:
        catalog.add("ok", "1", "m", uncertainty="-1")
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT
