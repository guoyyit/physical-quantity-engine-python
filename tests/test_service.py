import time

import pytest
from fastapi.testclient import TestClient

from pqe.service import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


def _settle(client, batch_id, attempts=50):
    for _ in range(attempts):
        data = client.get(f"/batch/{batch_id}").json()
        if data["status"] in ("COMPLETED", "CANCELLED"):
            return data
        time.sleep(0.02)
    raise AssertionError("batch never completed")


def test_health_and_units(client):
    assert client.get("/health").json()["status"] == "ok"
    assert "m" in client.get("/units").json()["units"]


def test_commit_evaluate_and_version_flow(client):
    resp = client.post("/catalog/commit", json={
        "entries": [
            {"name": "d", "value": "100", "unit": "km", "uncertainty": "0.5"}
        ]
    })
    assert resp.status_code == 200
    version = resp.json()["version"]

    result = client.post("/evaluate", json={
        "expression": "d / 2", "version": version, "outputUnit": "km"
    })
    assert result.status_code == 200
    body = result.json()
    assert body["value"] == "50.00"
    assert body["uncertainty"] == "0.25"
    assert body["unit"] == "km"

    version_doc = client.get(f"/catalog/versions/{version}").json()
    assert "d" in version_doc["entries"]


def test_stable_error_codes_and_http_status(client):
    assert client.post("/evaluate", json={"expression": "1+"}).json()[
        "error"]["code"] == "PARSE_ERROR"
    assert client.post("/evaluate", json={"expression": "z"}).json()[
        "error"]["code"] == "UNKNOWN_NAME"


def test_dimension_mismatch_flow(client):
    client.post("/catalog/commit", json={
        "entries": [{"name": "a", "value": "1", "unit": "m"}]
    })
    client.post("/catalog/commit", json={
        "entries": [{"name": "b", "value": "1", "unit": "s"}]
    })
    resp = client.post("/evaluate", json={"expression": "a + b"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "DIMENSION_MISMATCH"


def test_convert_endpoint(client):
    resp = client.post("/convert", json={
        "value": "100", "unit": "km/h", "targetUnit": "m/s"})
    assert resp.status_code == 200
    assert resp.json()["value"] == "27.7777777778"
    bad = client.post("/convert", json={
        "value": "1", "unit": "m", "targetUnit": "s"})
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "DIMENSION_MISMATCH"


def test_optimistic_conflict_returns_409(client):
    client.post("/catalog/commit", json={
        "entries": [{"name": "a", "value": "1", "unit": "m"}]})
    resp = client.post("/catalog/commit", json={
        "entries": [{"name": "b", "value": "1", "unit": "m"}],
        "baseVersion": 0,
    })
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "CATALOG_CONFLICT"


def test_batch_flow_and_cancel(client):
    resp = client.post("/batch", json={"items": [
        {"id": "i1", "expression": "1+1"},
        {"id": "i2", "expression": "1+"},
    ]})
    batch_id = resp.json()["batch_id"]
    data = _settle(client, batch_id)
    assert data["items"][0]["result"]["value"] == "2.00000000000"
    assert data["items"][1]["error"]["code"] == "PARSE_ERROR"

    cancel = client.post(f"/batch/{batch_id}/cancel")
    # The batch already completed, so late cancellation is refused rather
    # than mutating a finished result.
    assert cancel.status_code == 400
    assert cancel.json()["error"]["code"] == "INVALID_ARGUMENT"
    assert client.get("/batch/missing").status_code == 404


def test_validation_error_is_structured(client):
    resp = client.post("/evaluate", json={})
    assert resp.status_code == 422
    # Pydantic validation errors never masquerade as success.
    assert "detail" in resp.json()


def test_non_finite_and_exceptional_inputs_rejected(client):
    # Non-finite committed value.
    resp = client.post("/catalog/commit", json={
        "entries": [{"name": "bad", "value": "Infinity", "unit": "m"}]})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "NON_FINITE_VALUE"

    # Direct division by zero.
    resp = client.post("/evaluate", json={"expression": "1/0"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "DIVISION_BY_ZERO"

    # Unknown unit on commit.
    resp = client.post("/catalog/commit", json={
        "entries": [{"name": "x", "value": "1", "unit": "frob"}]})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "UNKNOWN_UNIT"


def test_no_null_or_fake_success_on_failure(client):
    resp = client.post("/evaluate", json={"expression": "a+b"})
    assert resp.status_code != 200
    body = resp.json()
    assert "error" in body and body["error"]["code"]
    assert "result" not in body
