"""Resume the public Zenodo CSV; only a provider-verified file is promoted."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request, urlopen
import hashlib
import os

URL = "https://zenodo.org/api/records/15786357/files/Java_VLM_EW.csv/content"
SIZE = 446891387
MD5 = "02ef53d4cb962e2c044fbf0d096824df"
DEST = Path("data/raw/published_java_15786357/Java_VLM_EW.csv")


def verified(path):
    if path.stat().st_size != SIZE:
        return False
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "md5").hexdigest() == MD5


def fetch(part):
    start, stop = part
    for attempt in range(3):
        try:
            with urlopen(
                Request(URL, headers={"Range": f"bytes={start}-{stop - 1}"}), timeout=45
            ) as r:
                if (
                    r.status != 206
                    or r.headers.get("Content-Range")
                    != f"bytes {start}-{stop - 1}/{SIZE}"
                ):
                    raise ValueError("Unexpected HTTP range")
                data = r.read(stop - start + 1)
                if len(data) != stop - start:
                    raise IOError("Short read")
                return data
        except (OSError, TimeoutError):
            if attempt == 2:
                raise


def main():
    if DEST.exists():
        if not verified(DEST):
            raise ValueError(
                "Existing CSV is not the registered source; not overwritten"
            )
        return
    DEST.parent.mkdir(parents=True, exist_ok=True)
    p = DEST.with_suffix(".csv.partial")
    start = p.stat().st_size if p.exists() else 0
    step = 4 * 1024**2
    parts = [(i, min(i + step, SIZE)) for i in range(start, SIZE, step)]
    with p.open("ab") as stream, ThreadPoolExecutor(4) as pool:
        for index in range(0, len(parts), 4):
            for data in pool.map(fetch, parts[index : index + 4]):
                stream.write(data)
            stream.flush()
    if not verified(p):
        raise ValueError("Full-file integrity failed; partial retained separately")
    os.link(p, DEST)  # exclusive; never overwrite
    p.unlink()
    print("Verified", DEST, flush=True)


if __name__ == "__main__":
    main()
