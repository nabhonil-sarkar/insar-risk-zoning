from scripts.analyze_v9_pair_loop_attribution import parse_ifg_stats


def test_parse_ifg_stats_reads_numeric_columns_and_skips_headers():
    records = parse_ifg_stats(
        """# ifg dates bperp dt unw_cov coh_av
20200102_20200114 -0.3 12 0.901 0.342
20200102_20200126 -0.2 24 0.610 0.332
"""
    )

    assert records == [
        {
            "pair": "20200102_20200114",
            "first": "20200102",
            "second": "20200114",
            "perpendicular_baseline": -0.3,
            "temporal_baseline_days": 12,
            "unwrapped_coverage": 0.901,
            "average_coherence": 0.342,
        },
        {
            "pair": "20200102_20200126",
            "first": "20200102",
            "second": "20200126",
            "perpendicular_baseline": -0.2,
            "temporal_baseline_days": 24,
            "unwrapped_coverage": 0.610,
            "average_coherence": 0.332,
        },
    ]
