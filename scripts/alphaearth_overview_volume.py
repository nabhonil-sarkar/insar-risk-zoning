"""Header-only upper bound for full-area GCS-only acquisition, without fetching blocks."""

from concurrent.futures import ThreadPoolExecutor
import math
from rasterio.io import MemoryFile
from scripts import alphaearth_overview_check as ov
from scripts import alphaearth_gcs_pilot as g


def tile_budget(tile, envelope):
    obj = tile["object"]
    header = ov.fetch(obj, (0, 256 * 1024))
    w, s, e, n = tile["native_bounds"]
    left, bottom, right, top = envelope
    with MemoryFile(header) as mem, mem.open(OVERVIEW_LEVEL="0") as src:
        if src.res != (20, 20) or src.crs.to_string() != tile["crs"] or src.count != 64:
            raise ValueError("Overview metadata changed")
        corners = [
            (~src.transform) * (x, y)
            for x in (max(w, left), min(e, right))
            for y in (max(s, bottom), min(n, top))
        ]
        cols, rows = zip(*corners)
        bh, bw = src.block_shapes[0]
        block_ids = [
            (i, j)
            for i in range(
                max(0, math.floor(min(rows) / bh)),
                min(math.ceil(src.height / bh), math.ceil(max(rows) / bh)),
            )
            for j in range(
                max(0, math.floor(min(cols) / bw)),
                min(math.ceil(src.width / bw), math.ceil(max(cols) / bw)),
            )
        ]
        total = 0
        for i, j in block_ids:
            for b in range(1, 65):
                size = src.get_tag_item(f"BLOCK_SIZE_{j}_{i}", "TIFF", bidx=b)
                offset = src.get_tag_item(f"BLOCK_OFFSET_{j}_{i}", "TIFF", bidx=b)
                if (not size) != (not offset):
                    raise ValueError("Invalid TIFF block")
                total += int(size or 0)
    return dict(
        year=tile["year"],
        name=obj["name"],
        generation=obj["generation"],
        spatial_blocks=len(block_ids),
        payload_bytes=total,
    )


def main():
    ov.verify()
    out = g.OUT / "gcs_only_v1" / "full_grid_volume.json"
    if out.exists():
        raise FileExistsError(out)
    inv = ov.checked_json(ov.INV)
    with ThreadPoolExecutor(4) as pool:
        rows = list(
            pool.map(
                lambda t: tile_budget(t, inv["projected_grid_envelope"]), inv["tiles"]
            )
        )
    g.write_new(
        out,
        dict(
            inventory_sha256=ov.PINS[ov.INV],
            tiles=rows,
            overview_payload_bytes=sum(r["payload_bytes"] for r in rows),
            basis="Stored 20 m compressed blocks intersecting projected rectangle envelope, all 64 axes, read once per object. Excludes headers, retries and outputs. No full tiles downloaded.",
        ),
    )


if __name__ == "__main__":
    main()
