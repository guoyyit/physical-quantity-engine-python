import threading
import time

import pytest

from pqengine.batch import BatchRunner, TaskRequest
from pqengine.catalog import Catalog
from pqengine.errors import ErrorCode
from pqengine.quantity import make_quantity
from pqengine.units import default_registry


@pytest.fixture
def reg():
    return default_registry()


@pytest.fixture
def runner(reg):
    r = BatchRunner(max_workers=4, registry=reg,
                    sleep_fn=lambda s: threading.Event().wait(s))
    yield r
    r.shutdown()


def task(tid, expr, **kw):
    return TaskRequest(tid, expr, {}, **kw)


def test_all_success(runner):
    results = runner.run([task("a", "1+2"), task("b", "6*7")])
    assert [r.ok for r in results] == [True, True]
    assert results[0].result.value == 3.0
    assert results[1].result.value == 42.0


def test_single_failure_isolated(runner):
    results = runner.run([
        task("ok", "1+1"),
        task("bad", "x"),                    # unknown quantity
        task("dim", "1 + 2"),
    ])
    assert results[0].ok and results[0].result.value == 2.0
    assert not results[1].ok
    assert results[1].error["code"] == ErrorCode.UNKNOWN_QUANTITY.value
    assert results[2].ok and results[2].result.value == 3.0


def test_dimension_mismatch_task(runner):
    vars_ = {
        "x": make_quantity(1.0, "m", registry=runner._registry),
        "t": make_quantity(1.0, "s", registry=runner._registry),
    }
    results = runner.run([TaskRequest("d", "x + t", vars_)])
    assert not results[0].ok
    assert results[0].error["code"] == ErrorCode.DIMENSION_MISMATCH.value


def test_timeout(runner):
    results = runner.run([
        task("slow", "1+1", sleep=1.0, timeout=0.1),
        task("fast", "1+1"),
    ])
    slow, fast = results
    assert not slow.ok
    assert slow.error["code"] == ErrorCode.TASK_TIMEOUT.value
    assert fast.ok


def test_cancellation(reg):
    runner = BatchRunner(
        max_workers=2, registry=reg,
        sleep_fn=lambda s: threading.Event().wait(s),
    )
    try:
        cancel = threading.Event()
        tasks = [task(f"t{i}", "1+1", sleep=0.5) for i in range(4)]

        def fire():
            time.sleep(0.1)
            cancel.set()

        threading.Thread(target=fire).start()
        results = runner.run(tasks, cancel=cancel)
        for r in results:
            assert not r.ok
            assert r.error["code"] == ErrorCode.TASK_CANCELLED.value
    finally:
        runner.shutdown()


def test_duplicate_ids_rejected(runner):
    from pqengine.errors import EngineError
    with pytest.raises(EngineError):
        runner.run([task("a", "1"), task("a", "2")])


def test_uses_catalog_version(reg):
    catalog = Catalog()
    catalog.commit({"x": make_quantity(1.0, "m", registry=reg)})
    catalog.commit({"x": make_quantity(2.0, "m", registry=reg)})
    runner = BatchRunner(max_workers=2, registry=reg, catalog=catalog)
    try:
        results = runner.run([
            TaskRequest("old", "x", {}, version=1),
            TaskRequest("new", "x", {}, version=2),
            TaskRequest("missing", "x", {}, version=99),
        ])
        assert results[0].result.value == 1.0
        assert results[1].result.value == 2.0
        assert not results[2].ok
        assert results[2].error["code"] == ErrorCode.VERSION_NOT_FOUND.value
    finally:
        runner.shutdown()


def test_no_partial_results(runner):
    # Every request produces exactly one terminal result record.
    tasks = [task("ok", "2^3"), task("fail", "1/0"),
             task("slow", "1", sleep=0.3, timeout=0.05)]
    results = runner.run(tasks)
    assert len(results) == 3
    for r in results:
        assert (r.result is None) ^ r.ok
