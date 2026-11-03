import pandas as pd
from scripts.audit_published_java import FIELDS, summarize


def test_conflicting_coords_are_not_averaged_or_counted_twice():
    rows = pd.DataFrame(
        [[106.5, -6.2, 1, 1, 2, 1]] * 2
        + [
            [106.6, -6.3, 1, 1, 2, 1],
            [106.6, -6.3, 2, 1, 2, 1],
            [106.7, -6.4, 0, 0, 2, 1],
        ],
        columns=FIELDS,
    )
    out = summarize(rows)
    assert out["roi_rows"] == 5 and out["unique_locations"] == 3
    assert out["eligible_unique_vertical_locations"] == 1
    assert (
        out["duplicate_rows_identical"]
        == out["conflicting_locations"]
        == out["withheld_nonpositive_or_missing_sd_or_rate"]
        == 1
    )
    assert out["occupied_001deg_bins"] == 1
