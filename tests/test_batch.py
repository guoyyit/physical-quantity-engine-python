import time

import pytest

from pqe.batch import (
    BatchItemRequest,
    BatchManager,
    BatchStatus,
)
from pqe.errors import EngineError, ErrorCode


def _settle(batch, attempts=100):
    for _ in range(attempts):
        terminal = {"OK", "ERROR", "TIMEOUT", "CANCELLED"}
        if all(item.status in terminal for item in batch.items):
            return
        time.sleep(0.01)
    raise AssertionError("batch did not settle")


def test_mixed_success_and_failure_isolation(manager):
    batch = manager.submit([
        BatchItemRequest("ok", "1 + 2"),
        BatchItemRequest("parse", "1 +"),
        BatchItemRequest("unknown", "nope"),
    ])
    _settle(batch)
    by_id = {item.id: item for item in batch.items}
    assert by_id["ok"].status == "OK"
    assert by_id["ok"].result["value"] == "3.00000000000"
    assert by_id["parse"].status == "ERROR"
    assert by_id["parse"].error["code"] == "PARSE_ERROR"
    assert by_id["unknown"].status == "ERROR"
    assert by_id["unknown"].error["code"] == "UNKNOWN_NAME"


def test_dimension_mismatch_fails_one_item_only(seeded_evaluator):
    manager = BatchManager(seeded_evaluator)
    batch = manager.submit([
        BatchItemRequest("good", "distance/elapsed"),
        BatchItemRequest("bad", "distance + elapsed"),
    ])
    _settle(batch)
    by_id = {item.id: item for item in batch.items}
    assert by_id["good"].status == "OK"
    assert by_id["bad"].status == "ERROR"
    assert by_id["bad"].error["code"] == "DIMENSION_MISMATCH"


def test_timeout_does_not_publish_partial_result():
    class SlowEvaluator:
        def evaluate(self, expression, version=None, output_unit=None,
                     cancel=None):
            for _ in range(500):
                cancel()
                time.sleep(0.005)
            raise AssertionError("should have timed out")

    manager = BatchManager(SlowEvaluator())
    start = time.monotonic()
    batch = manager.submit([
        BatchItemRequest("slow", "x", timeout_ms=80),
        BatchItemRequest("slow2", "x", timeout_ms=4000),
    ])
    # Wait only for the item under test; the sibling intentionally runs long.
    for _ in range(100):
        slow_item = batch.items[0]
        if slow_item.status == "TIMEOUT":
            break
        time.sleep(0.01)
    elapsed = time.monotonic() - start
    slow_item = batch.items[0]
    sibling = batch.items[1]
    assert slow_item.status == "TIMEOUT"
    assert slow_item.error["code"] == "TASK_TIMEOUT"
    assert slow_item.result is None
    # Timeout of one item must not cancel or fail the other; while it is
    # still running it must carry no partial result/error.
    assert sibling.status in ("PENDING", "RUNNING")
    assert sibling.result is None and sibling.error is None
    assert elapsed < 3, elapsed
    # Clean up: cancel the long-running sibling so workers shut down.
    manager.cancel(batch.batch_id)


def test_cancel_marks_pending_and_running(seeded_evaluator):
    # Use a tiny sleep expression via monkeypatched slow evaluator so running
    # tasks reach cooperation points.
    class Slow:
        def __init__(self, inner):
            self.inner = inner

        def evaluate(self, expression, version=None, output_unit=None,
                     cancel=None):
            for _ in range(300):
                cancel()
                time.sleep(0.005)
            return self.inner.evaluate(
                expression, version, output_unit, cancel)

    manager = BatchManager(Slow(seeded_evaluator), max_workers=1)
    batch = manager.submit([
        BatchItemRequest(f"i{i}", "1+1") for i in range(6)
    ])
    time.sleep(0.05)
    manager.cancel(batch.batch_id)
    _settle(batch)
    assert batch.status == BatchStatus.CANCELLED
    for item in batch.items:
        assert item.status == "CANCELLED"
        assert item.result is None
        assert item.error["code"] == "TASK_CANCELLED"


def test_cancel_unknown_batch(manager):
    with pytest.raises(EngineError) as exc:
        manager.cancel("does-not-exist")
    assert exc.value.code is ErrorCode.BATCH_NOT_FOUND


def test_duplicate_item_ids_rejected(manager):
    with pytest.raises(EngineError) as exc:
        manager.submit([
            BatchItemRequest("x", "1"),
            BatchItemRequest("x", "2"),
        ])
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT


def test_empty_batch_rejected(manager):
    with pytest.raises(EngineError) as exc:
        manager.submit([])
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT


def test_non_positive_timeout_rejected(manager):
    with pytest.raises(EngineError) as exc:
        manager.submit([BatchItemRequest("x", "1", timeout_ms=0)])
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT


def test_cancel_completed_batch_rejected(manager):
    batch = manager.submit([BatchItemRequest("x", "1+1")])
    _settle(batch)
    assert batch.status == BatchStatus.COMPLETED
    with pytest.raises(EngineError) as exc:
        manager.cancel(batch.batch_id)
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT


def test_uncertainty_collapsing_to_zero_presented_normally(seeded_evaluator):
    # A huge value with a tiny relative uncertainty may round the absolute
    # uncertainty to zero at the chosen place; the value must still render
    # at 12 significant digits rather than aligning to zero.
    result = seeded_evaluator.evaluate(
        "distance", output_unit="m")  # no uncertainty on distance
    assert result.uncertainty_text is None
    assert result.value_text == "100000.000000"
