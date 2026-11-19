"""Archive native provider payloads as content-addressed JSON files for reimport.

The archive records the input data before it is reduced to database columns. A canonical
JSON digest supplies a stable filename, while the file itself is indented for inspection.
Both the Alpaca quote and Amsterdam trade paths use this writer with their own archive
directory.
"""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from options_lab.domain import digest


def archive(raw: dict, directory: Path) -> Path:
    """Write raw to directory under its canonical SHA-256 digest and return its path.

    Create the directory if needed. If the content-addressed path already exists, return it
    directly. For a new archive, write indented JSON to a temporary file in the same
    directory and replace the final path only after the write succeeds. Temporary files are
    cleaned up after the attempt.

    raw must contain JSON-serializable data with finite numeric values. Serialization and
    filesystem errors propagate so the caller can report a failed capture. No database
    write occurs here.
    """
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{digest(raw)}.json"
    if not path.exists():
        with NamedTemporaryFile(mode="w", dir=directory, delete=False) as tmp:
            temp = Path(tmp.name)
            try:
                json.dump(raw, tmp, indent=2, allow_nan=False)
                tmp.write("\n")
                tmp.flush()
                temp.replace(path)
            finally:
                temp.unlink(missing_ok=True)
    return path
