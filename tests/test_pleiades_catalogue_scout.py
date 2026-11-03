from datetime import datetime, timezone
import pytest
from scripts import scout_pleiades_footprints as scout


@pytest.mark.parametrize(
    "case", ["valid", "wrong_year", "truncated", "wrong_id", "repeated_id"]
)
def test_public_metadata_cannot_silently_drop_or_misdate_scenes(monkeypatch, case):
    def get(url, p):
        if p.get("returnIdsOnly"):
            return {"objectIds": [1, 1] if case == "repeated_id" else [1]}
        d = datetime(2021 if case == "wrong_year" else 2020, 7, 1, tzinfo=timezone.utc)
        return {
            "exceededTransferLimit": case == "truncated",
            "features": [
                {
                    "properties": {
                        "objectid": 2 if case == "wrong_id" else 1,
                        "acquisitiondate": int(d.timestamp() * 1000),
                    }
                }
            ],
        }

    monkeypatch.setattr(scout.wb, "get", get)
    if case == "valid":
        assert len(scout.get_year(2020)) == 1
    else:
        with pytest.raises(ValueError):
            scout.get_year(2020)
