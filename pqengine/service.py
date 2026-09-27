"""FastAPI service exposing evaluation, catalog and batch endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .batch import BatchRunner, TaskRequest
from .catalog import Catalog
from .errors import EngineError, ErrorCode
from .evaluator import Evaluator
from .parser import parse
from .quantity import Quantity, make_quantity
from .units import UnitRegistry, default_registry


def _quantity_to_dict(q: Quantity) -> dict[str, Any]:
    return {
        "value": q.value,
        "unit": q.unit.name,
        "uncertainty": q.uncertainty,
        "dimension": list(q.unit.dimension.exponents),
    }


def create_app(registry: UnitRegistry | None = None,
               catalog: Catalog | None = None,
               runner: BatchRunner | None = None) -> FastAPI:
    app = FastAPI(title="Physical Quantity Engine", version="0.1.0")
    app.state.registry = registry if registry is not None else default_registry()
    app.state.catalog = catalog if catalog is not None else Catalog()
    app.state.runner = runner if runner is not None else BatchRunner(
        max_workers=8,
        registry=app.state.registry,
        catalog=app.state.catalog,
    )

    @app.exception_handler(EngineError)
    async def engine_error_handler(_: Request, exc: EngineError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"error": exc.to_dict()})

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/evaluate")
    async def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
        expression = payload.get("expression")
        if not isinstance(expression, str):
            raise EngineError(
                ErrorCode.INVALID_REQUEST,
                "'expression' is required and must be a string",
            )
        version = payload.get("version")
        variables = _build_variables(
            payload.get("variables", {}), app.state.registry,
            app.state.catalog, version,
        )
        tree = parse(expression)
        result = Evaluator(variables, app.state.registry).eval(tree)
        return {"result": _quantity_to_dict(result)}

    @app.get("/catalog/versions")
    async def list_versions() -> dict[str, Any]:
        return {"versions": app.state.catalog.list_versions()}

    @app.get("/catalog/versions/{version}")
    async def get_version(version: int) -> dict[str, Any]:
        snapshot = app.state.catalog.get_version(version)
        return {
            "version": snapshot.version,
            "entries": {
                name: _quantity_to_dict(q)
                for name, q in snapshot.entries.items()
            },
        }

    @app.post("/catalog/commit")
    async def commit(payload: dict[str, Any]) -> dict[str, Any]:
        raw_entries = payload.get("entries")
        if not isinstance(raw_entries, dict):
            raise EngineError(
                ErrorCode.INVALID_REQUEST,
                "'entries' is required and must be an object of name -> quantity",
            )
        expected_version = payload.get("expected_version")
        entries = {
            name: _quantity_from_spec(name, spec, app.state.registry)
            for name, spec in raw_entries.items()
        }
        snapshot = app.state.catalog.commit(entries, expected_version)
        return {"version": snapshot.version, "count": len(snapshot.entries)}

    @app.post("/batch")
    async def batch(payload: dict[str, Any]) -> dict[str, Any]:
        raw_tasks = payload.get("tasks")
        if not isinstance(raw_tasks, list):
            raise EngineError(
                ErrorCode.INVALID_REQUEST, "'tasks' must be a list"
            )
        requests: list[TaskRequest] = []
        for item in raw_tasks:
            tid = item.get("id")
            expr = item.get("expression")
            if not isinstance(tid, str) or not isinstance(expr, str):
                raise EngineError(
                    ErrorCode.INVALID_REQUEST,
                    "each task requires string 'id' and 'expression'",
                )
            raw_variables = item.get("variables", {})
            version = item.get("version")
            # Defer spec parsing and version resolution into the worker so a
            # bad task (e.g. missing version) cannot fail the whole batch.
            def _build(raw: object = raw_variables, ver: object = version):
                return _build_variables(
                    raw, app.state.registry, app.state.catalog, ver
                )

            requests.append(TaskRequest(
                id=tid, expression=expr, variables={},
                version=version if isinstance(version, int)
                and not isinstance(version, bool) else None,
                timeout=item.get("timeout"),
                sleep=float(item.get("sleep", 0.0)),
                variable_builder=_build,
            ))
        results = app.state.runner.run(requests)
        return {
            "results": [
                {
                    "id": r.id,
                    "ok": r.ok,
                    "result": _quantity_to_dict(r.result) if r.result else None,
                    "error": r.error,
                }
                for r in results
            ]
        }

    return app


def _quantity_from_spec(name: Any, spec: Any,
                        registry: UnitRegistry) -> Quantity:
    if not isinstance(name, str) or not name:
        raise EngineError(
            ErrorCode.INVALID_REQUEST, "quantity name must be a non-empty string"
        )
    if not isinstance(spec, dict):
        raise EngineError(
            ErrorCode.INVALID_REQUEST, f"quantity {name!r} must be an object"
        )
    value = spec.get("value")
    unit = spec.get("unit")
    uncertainty = spec.get("uncertainty", 0.0)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise EngineError(
            ErrorCode.INVALID_REQUEST,
            f"quantity {name!r}: 'value' must be a number",
        )
    if not isinstance(unit, str):
        raise EngineError(
            ErrorCode.INVALID_REQUEST,
            f"quantity {name!r}: 'unit' must be a string",
        )
    if not isinstance(uncertainty, (int, float)) or isinstance(uncertainty, bool):
        raise EngineError(
            ErrorCode.INVALID_REQUEST,
            f"quantity {name!r}: 'uncertainty' must be a number",
        )
    return make_quantity(float(value), unit, float(uncertainty), registry)


def _build_variables(raw: Any, registry: UnitRegistry,
                     catalog: Catalog, version: Any) -> dict[str, Quantity]:
    if not isinstance(raw, dict):
        raise EngineError(
            ErrorCode.INVALID_REQUEST, "'variables' must be an object"
        )
    variables: dict[str, Quantity] = {}
    if version is not None:
        if not isinstance(version, int) or isinstance(version, bool):
            raise EngineError(
                ErrorCode.INVALID_REQUEST, "'version' must be an integer"
            )
        snapshot = catalog.get_version(version)
        variables.update(snapshot.entries)
    for name, spec in raw.items():
        variables[name] = _quantity_from_spec(name, spec, registry)
    return variables


app = create_app()
