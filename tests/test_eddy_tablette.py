import pytest
from eddy.perception.tablette import SourceTablette

def test_rasterise_produit_un_png():
    PIL = pytest.importorskip("PIL")  # noqa: F841
    from eddy.perception.tablette import rasterise
    traits = [[(10, 10), (20, 20), (30, 10)]]   # un trait, 3 points
    data = rasterise(traits, taille=(64, 64))
    assert data[:8] == b"\x89PNG\r\n\x1a\n"      # magie PNG
    assert len(data) > 8

def test_source_tablette_collecte_puis_rasterise():
    # collecte injectée → pas besoin de matériel ; encode injecté → pas de PIL.
    src = SourceTablette(collecte=lambda: [[(1, 1), (2, 2)]],
                         encode=lambda traits: b"\x89PNG_fake")
    data = src.capture()
    assert data == b"\x89PNG_fake"
    assert src.canal == "tablette"
