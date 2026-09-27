"""Isolated, cancellable, timeout-bounded batch evaluation tasks.

Each task runs independently in a worker thread.  A failure in one task
is captured into its own :class:`TaskResult` and never affects the others.
Cancellation and timeout produce terminal error results and never leave
partial task output behind: a task exposes a result exactly once, either
successful or failed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from dataclasses import dataclass

from .catalog import Catalog
from .errors import EngineError, ErrorCode
from .evaluator import Evaluator
from .parser import parse
from .quantity import Quantity
from .units import UnitRegistry, default_registry


@dataclass(frozen=True)
class TaskRequest:
    id: str
    expression: str
    variables: dict[str, Quantity]
    version: int | None = None
    timeout: float | None = None
    sleep: float = 0.0  # test hook for deterministic timeout simulation
    # Optional deferred builder (e.g. parses raw specs and resolves a catalog
    # version).  Invoked inside the worker so its failure is isolated.
    variable_builder: Callable[[], dict[str, Quantity]] | None = None


@dataclass(frozen=True)
class TaskResult:
    id: str
    ok: bool
    result: Quantity | None = None
    error: dict[str, str] | None = None


def _cancelled_error(task_id: str) -> dict[str, str]:
    return {
        "code": ErrorCode.TASK_CANCELLED.value,
        "message": f"task {task_id!r} was cancelled",
    }


def _timeout_error(task_id: str) -> dict[str, str]:
    return {
        "code": ErrorCode.TASK_TIMEOUT.value,
        "message": f"task {task_id!r} exceeded its timeout",
    }


def _failed(task_id: str, error: dict[str, str]) -> TaskResult:
    return TaskResult(task_id, False, None, error)


class BatchRunner:
    def __init__(self, max_workers: int = 4,
                 registry: UnitRegistry | None = None,
                 catalog: Catalog | None = None,
                 sleep_fn: Callable[[float], None] | None = None) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="pqtask",
        )
        self._registry = registry if registry is not None else default_registry()
        self._catalog = catalog
        self._sleep = sleep_fn if sleep_fn is not None else threading.Event().wait

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=True)

    # -- execution -------------------------------------------------------

    def _run_one(self, task: TaskRequest,
                 cancel: threading.Event) -> TaskResult:
        try:
            if task.sleep and self._sleep(task.sleep):
                return _failed(task.id, _cancelled_error(task.id))
            if cancel.is_set():
                return _failed(task.id, _cancelled_error(task.id))

            variables = dict(task.variables)
            if task.variable_builder is not None:
                # Failure here (bad spec, missing version) stays in this task.
                variables = task.variable_builder()
            elif self._catalog is not None and task.version is not None:
                snapshot = self._catalog.get_version(task.version)
                # Snapshot entries provide defaults; inline variables win.
                merged = dict(snapshot.entries)
                merged.update(variables)
                variables = merged
            if cancel.is_set():
                return _failed(task.id, _cancelled_error(task.id))

            tree = parse(task.expression)
            if cancel.is_set():
                return _failed(task.id, _cancelled_error(task.id))

            result = Evaluator(variables, self._registry).eval(tree)
            if cancel.is_set():
                return _failed(task.id, _cancelled_error(task.id))
            return TaskResult(task.id, True, result, None)
        except EngineError as exc:
            return _failed(task.id, exc.to_dict())
        except Exception as exc:  # noqa: BLE001 - intentional task isolation
            return _failed(task.id, {
                "code": ErrorCode.TASK_FAILED.value,
                "message": f"task {task.id!r} failed: {exc}",
            })

    def run(self, tasks: list[TaskRequest],
            cancel: threading.Event | None = None) -> list[TaskResult]:
        if cancel is None:
            cancel = threading.Event()
        ids = [t.id for t in tasks]
        if len(set(ids)) != len(ids):
            raise EngineError(
                ErrorCode.INVALID_REQUEST, "task ids must be unique"
            )

        pairs = [(task, self._executor.submit(
            self._run_one, task, cancel)) for task in tasks]
        results: dict[str, TaskResult] = {}
        for task, future in pairs:
            try:
                results[task.id] = future.result(timeout=task.timeout)
            except FuturesTimeout:
                future.cancel()
                results[task.id] = _failed(task.id, _timeout_error(task.id))
            except Exception as exc:  # noqa: BLE001 - never break the batch
                results[task.id] = _failed(task.id, {
                    "code": ErrorCode.TASK_FAILED.value,
                    "message": f"task {task.id!r} failed: {exc}",
                })
        return [results[task.id] for task in tasks]
