"""FastAPI HTTP surface for the physical-quantity evaluation service."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .batch import BatchItemRequest, BatchManager, BatchStatus
from .catalog import Catalog
from .errors import EngineError
from .evaluator import Evaluator
from .units import UnitSystem

_HTTP_STATUS = {
    "PARSE_ERROR": 400,
    "UNKNOWN_NAME": 404,
    "UNKNOWN_UNIT": 400,
    "DIMENSION_MISMATCH": 422,
    "INVALID_ARGUMENT": 400,
    "NON_FINITE_VALUE": 422,
    "OVERFLOW": 422,
    "DIVISION_BY_ZERO": 422,
    "UNIT_CONVERSION_FAILED": 422,
    "VERSION_NOT_FOUND": 404,
    "CATALOG_CONFLICT": 409,
    "TASK_TIMEOUT": 408,
    "TASK_CANCELLED": 499,
    "BATCH_NOT_FOUND": 404,
    "INTERNAL_ERROR": 500,
}


# -- request / response models -------------------------------------------
class EvaluateRequest(BaseModel):
    expression: str
    version: int | None = None
    output_unit: str | None = Field(default=None, alias="outputUnit")


class ConvertRequest(BaseModel):
    value: str
    unit: str
    target_unit: str = Field(alias="targetUnit")
    uncertainty: str | None = None


class CatalogEntryRequest(BaseModel):
    name: str
    value: str
    unit: str
    uncertainty: str | None = None


class CommitRequest(BaseModel):
    entries: list[CatalogEntryRequest]
    base_version: int | None = Field(default=None, alias="baseVersion")


class BatchEvaluateRequest(BaseModel):
    items: list[BatchItemRequest]


def build_engine() -> tuple[Catalog, Evaluator, BatchManager, UnitSystem]:
    units = UnitSystem()
    catalog = Catalog(units)
    evaluator = Evaluator(catalog, units)
    manager = BatchManager(evaluator)
    return catalog, evaluator, manager, units


def create_app() -> FastAPI:
    catalog, evaluator, manager, _ = build_engine()
    app = FastAPI(
        title="Physical Quantity Evaluation Service",
        version="0.1.0",
    )

    @app.exception_handler(EngineError)
    async def engine_error_handler(request, exc: EngineError):
        status = _HTTP_STATUS.get(exc.code.value, 500)
        return JSONResponse(status_code=status, content=exc.to_dict())

    @app.get("/health")
    def health():
        return {"status": "ok", "head_version": catalog.head_version()}

    @app.get("/units")
    def list_units():
        return {"units": units_safe(evaluator)}

    @app.get("/catalog/versions/{version}")
    def get_version(version: int):
        snap = catalog.get_version(version)
        return {
            "version": snap.version,
            "entries": {
                name: {
                    "value": str(entry.value),
                    "unit": entry.unit,
                    "uncertainty": (str(entry.uncertainty)
                                    if entry.uncertainty is not None else None),
                    "dimension": list(entry.dimension.exponents),
                }
                for name, entry in snap.entries.items()
            },
        }

    @app.post("/catalog/commit")
    def commit_catalog(req: CommitRequest):
        from .catalog import CatalogEntry
        entries = {
            e.name: catalog.make_entry(e.name, e.value, e.unit, e.uncertainty)
            for e in req.entries
        }
        snap = catalog.commit(entries, req.base_version)
        return {"version": snap.version,
                "entry_count": len(snap.entries)}

    @app.post("/evaluate")
    def evaluate(req: EvaluateRequest):
        result = evaluator.evaluate(
            expression=req.expression,
            version=req.version,
            output_unit=req.output_unit,
        )
        return result.to_dict()

    @app.post("/convert")
    def convert(req: ConvertRequest):
        return evaluator.convert(
            value=req.value,
            unit=req.unit,
            target_unit=req.target_unit,
            uncertainty=req.uncertainty,
        )

    @app.post("/batch")
    def submit_batch(req: BatchEvaluateRequest):
        batch = manager.submit(req.items)
        return {"batch_id": batch.batch_id, "status": batch.status.value}

    @app.get("/batch/{batch_id}")
    def get_batch(batch_id: str):
        batch = manager.get(batch_id)
        return {
            "batch_id": batch.batch_id,
            "status": batch.status.value,
            "items": [
                {
                    "id": item.id,
                    "status": item.status,
                    "result": item.result,
                    "error": item.error,
                }
                for item in batch.items
            ],
        }

    @app.post("/batch/{batch_id}/cancel")
    def cancel_batch(batch_id: str):
        batch = manager.cancel(batch_id)
        return {"batch_id": batch.batch_id, "status": batch.status.value}

    return app


def units_safe(evaluator: Evaluator):
    return evaluator.units.known_units()
