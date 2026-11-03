import pytest
from scripts.alphaearth_six_year_sample import support, change, PAIRS, EDGES


def test_sample_scope_and_cosine_contract():
    assert len(EDGES) == len(set(EDGES)) == 18
    assert PAIRS == [
        (2020, 2021),
        (2021, 2022),
        (2022, 2023),
        (2023, 2024),
        (2024, 2025),
        (2020, 2023),
        (2020, 2025),
    ]
    a = support([10] * 64)
    assert change(a, 2 * a) == pytest.approx(0)
    assert change(a, -a) == pytest.approx(2)
    assert support([-128] * 64) is None and support([0] * 64) is None
    with pytest.raises(ValueError):
        support([-128] + [10] * 63)
