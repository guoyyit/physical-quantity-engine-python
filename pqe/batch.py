"""Isolated, cancellable, timeout-aware batch evaluation tasks.

Each item runs independently in a worker thread:

* one item raising an :class:`EngineError` only fills that item's ``error``;
* ``timeout_ms`` triggers TASK_TIMEOUT for that item;
* cancelling a batch marks not-started items TASK_CANCELLED and asks running
  items to stop through a cooperative cancellation event;
* results are only published for items that actually finished, so timeout or
  cancellation never leaves partial item output.
"""
from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum

from .errors import EngineError, ErrorCode
from .evaluator import Evaluator


class BatchStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


@dataclass(frozen=True)
class BatchItemRequest:
    id: str
    expression: str
    version: int | None = None
    output_unit: str | None = None
    timeout_ms: int = 10000


@dataclass
class BatchItemResult:
    id: str
    status: str                       # OK | ERROR | TIMEOUT | CANCELLED
    result: dict | None = None
    error: dict | None = None


@dataclass
class Batch:
    batch_id: str
    status: BatchStatus
    items: list[BatchItemResult] = field(default_factory=list)
    cancel_event: threading.Event = field(
        default_factory=threading.Event, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)


class BatchManager:
    def __init__(self, evaluator: Evaluator, max_workers: int = 4) -> None:
        self.evaluator = evaluator
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="batch")
        self._batches: dict[str, Batch] = {}
        self._lock = threading.Lock()

    # -- lifecycle --------------------------------------------------------
    def submit(self, items: list[BatchItemRequest]) -> Batch:
        self._validate_items(items)
        batch_id = uuid.uuid4().hex
        batch = Batch(
            batch_id=batch_id,
            status=BatchStatus.RUNNING,
            items=[BatchItemResult(item.id, "PENDING") for item in items],
        )
        cancel_event = batch.cancel_event
        with self._lock:
            self._batches[batch_id] = batch

        futures = []
        for index, item in enumerate(items):
            futures.append(self._executor.submit(
                self._run_item, batch, cancel_event, index, item))

        def waiter() -> None:
            # Always join every worker so RUNNING items settle into a final
            # status (OK/ERROR/TIMEOUT/CANCELLED), even after cancellation.
            for fut in futures:
                try:
                    fut.result()
                except Exception:  # defensive: item handler must not raise
                    pass
            with batch._lock:
                if batch.status == BatchStatus.RUNNING:
                    batch.status = BatchStatus.COMPLETED

        watcher = threading.Thread(target=waiter, daemon=True,
                                   name=f"batch-{batch_id}-join")
        watcher.start()
        return batch

    def get(self, batch_id: str) -> Batch:
        with self._lock:
            batch = self._batches.get(batch_id)
        if batch is None:
            raise EngineError(
                ErrorCode.BATCH_NOT_FOUND,
                f"batch {batch_id!r} does not exist")
        return batch

    def cancel(self, batch_id: str) -> Batch:
        batch = self.get(batch_id)
        with batch._lock:
            if batch.status not in (BatchStatus.RUNNING, BatchStatus.PENDING):
                raise EngineError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"batch {batch_id!r} is already {batch.status.value} "
                    f"and cannot be cancelled")
            batch.status = BatchStatus.CANCELLED
            # Signal every running item to stop at its next cooperation
            # point; pending items are marked cancelled immediately.
            batch.cancel_event.set()
            for item in batch.items:
                if item.status == "PENDING":
                    item.status = "CANCELLED"
                    item.error = {
                        "code": ErrorCode.TASK_CANCELLED.value,
                        "message": "task was cancelled before execution",
                    }
        return batch

    # -- internals --------------------------------------------------------
    def _validate_items(self, items: list[BatchItemRequest]) -> None:
        if not isinstance(items, list) or not items:
            raise EngineError(
                ErrorCode.INVALID_ARGUMENT,
                "batch must contain at least one item")
        seen: set[str] = set()
        for item in items:
            if item.id in seen:
                raise EngineError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"duplicate item id {item.id!r}")
            seen.add(item.id)
            if not isinstance(item.timeout_ms, int) or item.timeout_ms <= 0:
                raise EngineError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"timeout_ms for item {item.id!r} must be positive")

    def _run_item(self, batch: Batch, cancel_event: threading.Event,
                  index: int, item: BatchItemRequest) -> None:
        slot = batch.items[index]
        with batch._lock:
            if batch.status == BatchStatus.CANCELLED:
                slot.status = "CANCELLED"
                slot.error = self._error(
                    ErrorCode.TASK_CANCELLED,
                    "task was cancelled before execution")
                return
            assert slot.status == "PENDING"
            slot.status = "RUNNING"

        result_holder: dict = {}
        done = threading.Event()
        # Per-item cooperative stop: set on batch cancel or item timeout.
        item_stop = threading.Event()

        def _on_cancel_set() -> None:
            cancel_event.wait()
            item_stop.set()

        watcher = threading.Thread(target=_on_cancel_set, daemon=True)
        watcher.start()

        def work() -> None:
            try:
                res = self.evaluator.evaluate(
                    expression=item.expression,
                    version=item.version,
                    output_unit=item.output_unit,
                    cancel=lambda: self._raise_if_set(item_stop),
                )
                result_holder["result"] = res.to_dict()
            except EngineError as exc:
                result_holder["error"] = exc.to_dict()["error"]
            except Exception as exc:  # never let a worker die silently
                result_holder["error"] = {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": f"unexpected failure: {type(exc).__name__}: {exc}",
                }
            finally:
                done.set()

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        finished = done.wait(timeout=item.timeout_ms / 1000.0)
        with batch._lock:
            if not finished:
                # Ask the runaway task to stop cooperatively; no partial
                # result is published for this item.
                item_stop.set()
                if slot.status == "CANCELLED":
                    self._maybe_complete(batch)
                    return
                slot.status = "TIMEOUT"
                slot.error = self._error(
                    ErrorCode.TASK_TIMEOUT,
                    f"item {item.id!r} exceeded {item.timeout_ms} ms")
                self._maybe_complete(batch)
                return
            if slot.status == "CANCELLED":
                self._maybe_complete(batch)
                return
            if item_stop.is_set() and "error" in result_holder and \
                    result_holder["error"].get("code") == \
                    ErrorCode.TASK_CANCELLED.value:
                slot.status = "CANCELLED"
                slot.error = self._error(
                    ErrorCode.TASK_CANCELLED, "task was cancelled")
                self._maybe_complete(batch)
                return
            if "error" in result_holder:
                slot.status = "ERROR"
                slot.error = result_holder["error"]
            else:
                slot.status = "OK"
                slot.result = result_holder["result"]
            self._maybe_complete(batch)

    @staticmethod
    def _terminal(status: str) -> bool:
        return status in ("OK", "ERROR", "TIMEOUT", "CANCELLED")

    def _maybe_complete(self, batch: Batch) -> None:
        """Advance the batch to COMPLETED as soon as every item is terminal.

        Called while holding ``batch._lock`` so the batch status never
        lags behind the final item's status.
        """
        if batch.status == BatchStatus.RUNNING and all(
                self._terminal(item.status) for item in batch.items):
            batch.status = BatchStatus.COMPLETED

    @staticmethod
    def _raise_if_set(event: threading.Event) -> None:
        if event.is_set():
            raise EngineError(
                ErrorCode.TASK_CANCELLED, "task was cancelled")

    @staticmethod
    def _error(code: ErrorCode, message: str) -> dict:
        return {"code": code.value, "message": message}
