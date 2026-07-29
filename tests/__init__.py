"""Test-suite bootstrap with an isolated writable application root."""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import tempfile


_temporary_user_data: Path | None = None

if not os.environ.get("BDO_USER_DATA_DIR"):
    _temporary_user_data = Path(tempfile.mkdtemp(prefix="bdo-composer-tests-"))
    os.environ["BDO_USER_DATA_DIR"] = str(_temporary_user_data)


@atexit.register
def _remove_temporary_user_data() -> None:
    if _temporary_user_data is not None:
        shutil.rmtree(_temporary_user_data, ignore_errors=True)
