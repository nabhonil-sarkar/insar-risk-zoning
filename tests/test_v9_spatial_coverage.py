import numpy as np
from rasterio.transform import from_origin

from scripts.analyze_v9_spatial_coverage import connected_component_records


def test_connected_component_records_use_eight_neighbour_connectivity():
    strict = np.array(
        [
            [True, False, False, False],
            [False, True, False, True],
            [False, False, False, True],
        ]
    )
    velocity = np.array(
        [
            [-2.0, np.nan, np.nan, np.nan],
            [np.nan, 4.0, np.nan, 8.0],
            [np.nan, np.nan, np.nan, 10.0],
        ],
        dtype="float32",
    )
    dki = np.ones_like(strict)

    labels, records = connected_component_records(
        strict, velocity, dki, from_origin(106.0, -6.0, 0.005, 0.005)
    )

    assert labels.max() == 2
    assert [record["pixels"] for record in records] == [2, 2]
    assert records[0]["velocity_median_mmyr"] == 1.0
    assert records[1]["velocity_median_mmyr"] == 9.0
