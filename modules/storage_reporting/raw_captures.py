"""Store the original capture as JSON, addressed by its content hash."""

import json
from pathlib import Path
from tempfile import NamedTemporaryFile

from options_lab.domain import digest


def archive(raw: dict, directory: Path) -> Path:
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
