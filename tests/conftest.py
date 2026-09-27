import pytest

from pqe.batch import BatchManager
from pqe.catalog import Catalog
from pqe.evaluator import Evaluator
from pqe.units import UnitSystem


@pytest.fixture
def units():
    return UnitSystem()


@pytest.fixture
def catalog(units):
    return Catalog(units)


@pytest.fixture
def evaluator(catalog, units):
    return Evaluator(catalog, units)


@pytest.fixture
def manager(evaluator):
    return BatchManager(evaluator, max_workers=2)


@pytest.fixture
def seeded_catalog(catalog):
    """Catalog with distance, time and an uncertain acceleration."""
    catalog.add("distance", "100", "km")
    catalog.add("elapsed", "2", "h")
    catalog.add("accel", "9.8", "m/s^2", uncertainty="0.1")
    return catalog


@pytest.fixture
def seeded_evaluator(seeded_catalog, units):
    return Evaluator(seeded_catalog, units)
