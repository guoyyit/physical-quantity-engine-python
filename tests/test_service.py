import pytest
from fastapi.testclient import TestClient

from pqengine.batch import BatchRunner
from pqengine.catalog import Catalog
from pqengine.service import create_app
from pqengine.units import default_registry


@pytest.fixture
def client():
    catalog = Catalog()
    runner = BatchRunner(max_workers=4, registry=default_registry(),
                         catalog=catalog)
    app = create_app(registry=default_registry(), catalog=catalog,
                     runner=runner)
    with TestClient(app) as c:
        yield c
    runner.shutdown()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_evaluate_scalar(client):
    r = client.post("/evaluate", json={"expression": "2 + 3"})
    assert r.status_code == 200
    body = r.json()["result"]
    assert body["value"] == 5.0
    assert body["uncertainty"] == 0.0


def test_evaluate_with_units_and_uncertainty(client):
    r = client.post("/evaluate", json={
        "expression": "x / t",
        "variables": {
            "x": {"value": 10.0, "unit": "m", "uncertainty": 0.1},
            "t": {"value": 2.0, "unit": "s", "uncertainty": 0.01},
        },
    })
    assert r.status_code == 200
    result = r.json()["result"]
    assert result["value"] == 5.0
    assert result["uncertainty"] > 0


def test_dimension_mismatch_error_code(client):
    r = client.post("/evaluate", json={
        "expression": "x + t",
        "variables": {
            "x": {"value": 1.0, "unit": "m"},
            "t": {"value": 1.0, "unit": "s"},
        },
    })
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "DIMENSION_MISMATCH"
    assert error["message"]


def test_parse_error(client):
    r = client.post("/evaluate", json={"expression": "x +"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "PARSE_ERROR"


def test_invalid_request_missing_expression(client):
    r = client.post("/evaluate", json={})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_REQUEST"


def test_catalog_commit_and_versioned_eval(client):
    r = client.post("/catalog/commit", json={
        "expected_version": 0,
        "entries": {"x": {"value": 3.0, "unit": "m"}},
    })
    assert r.status_code == 200
    assert r.json()["version"] == 1

    r = client.post("/evaluate", json={"expression": "x * 2", "version": 1})
    assert r.status_code == 200
    assert r.json()["result"]["value"] == 6.0

    # Second commit replacing the catalog.
    r = client.post("/catalog/commit", json={
        "expected_version": 1,
        "entries": {"x": {"value": 4.0, "unit": "m"}},
    })
    assert r.json()["version"] == 2

    # Stale version rejected.
    r = client.post("/catalog/commit", json={
        "expected_version": 1,
        "entries": {},
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "CATALOG_CONFLICT"

    versions = client.get("/catalog/versions").json()["versions"]
    assert versions == [0, 1, 2]
    v1 = client.get("/catalog/versions/1").json()
    assert v1["entries"]["x"]["value"] == 3.0


def test_version_not_found(client):
    r = client.post("/evaluate", json={"expression": "1", "version": 42})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VERSION_NOT_FOUND"


def test_batch_isolation(client):
    r = client.post("/batch", json={"tasks": [
        {"id": "a", "expression": "1+1"},
        {"id": "b", "expression": "1/0"},
        {"id": "c", "expression": "2^3"},
    ]})
    assert r.status_code == 200
    results = {item["id"]: item for item in r.json()["results"]}
    assert results["a"]["ok"] and results["a"]["result"]["value"] == 2.0
    assert not results["b"]["ok"]
    assert results["b"]["error"]["code"] == "DIVISION_BY_ZERO"
    assert results["c"]["ok"] and results["c"]["result"]["value"] == 8.0


def test_batch_timeout(client):
    r = client.post("/batch", json={"tasks": [
        {"id": "slow", "expression": "1", "sleep": 1.0, "timeout": 0.05},
        {"id": "fast", "expression": "2"},
    ]})
    results = {item["id"]: item for item in r.json()["results"]}
    assert results["slow"]["error"]["code"] == "TASK_TIMEOUT"
    assert results["fast"]["ok"]


def test_unknown_unit_error(client):
    r = client.post("/evaluate", json={
        "expression": "x",
        "variables": {"x": {"value": 1.0, "unit": "frobnicate"}},
    })
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "UNKNOWN_UNIT"


def test_unit_conversion_endpoint_via_quantity(client):
    # Pressure * volume yields energy: 1 bar * 1 m^3 = 1e5 J.
    r = client.post("/evaluate", json={
        "expression": "x * y",
        "variables": {
            "x": {"value": 1.0, "unit": "m^3"},
            "y": {"value": 1.0, "unit": "bar"},
        },
    })
    assert r.status_code == 200
    assert r.json()["result"]["value"] == 1e5
    assert r.json()["result"]["unit"] == "J"


def test_batch_isolates_bad_version(client):
    # A missing version in one task must not fail the whole batch.
    r = client.post("/batch", json={"tasks": [
        {"id": "good", "expression": "1+1"},
        {"id": "ghost", "expression": "1", "version": 99},
        {"id": "badspec", "expression": "x",
         "variables": {"x": {"value": 1, "unit": "nope"}}},
    ]})
    assert r.status_code == 200
    results = {item["id"]: item for item in r.json()["results"]}
    assert results["good"]["ok"] and results["good"]["result"]["value"] == 2.0
    assert not results["ghost"]["ok"]
    assert results["ghost"]["error"]["code"] == "VERSION_NOT_FOUND"
    assert not results["badspec"]["ok"]
    assert results["badspec"]["error"]["code"] == "UNKNOWN_UNIT"
