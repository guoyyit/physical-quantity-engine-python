def test_imports():
    import pqengine
    from pqengine.service import app
    assert app is not None
    assert pqengine.__version__ == "0.1.0"
