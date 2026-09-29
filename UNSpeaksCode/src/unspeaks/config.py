"""Settings for UNSpeaks: where local data lives and how we talk to UN servers.

The request limits below come from the guidance the Dag Hammarskjöld Library
gave this project (see the README, "Terms of use"). Don't raise them.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PROJECT_URL = "https://github.com/GetOutOfMahSwamp/UNSpeaks"

try:
    VERSION = version("unspeaks")
except PackageNotFoundError:  # running from source without installing
    VERSION = "0.0.0"


def data_dir() -> Path:
    """Folder for local data (datasets and caches). It is never committed to Git.

    Set the UNSPEAKS_DATA_DIR environment variable to use another folder. By
    default this is the `data/` folder at the root of the UNSpeaks repository,
    next to `UNSpeaksCode/`.
    """
    override = os.environ.get("UNSPEAKS_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    # src/unspeaks/config.py -> [0] unspeaks, [1] src, [2] UNSpeaksCode, [3] repo root
    return Path(__file__).resolve().parents[3] / "data"


def user_agent() -> str:
    """An honest User-Agent: who we are and where to find us.

    Set UNSPEAKS_CONTACT_EMAIL to add a contact address (kept out of the code so
    it isn't published in the repository).
    """
    contact = os.environ.get("UNSPEAKS_CONTACT_EMAIL", "").strip()
    extra = f"; {contact}" if contact else ""
    return f"UNSpeaks/{VERSION} (+{PROJECT_URL}{extra})"


# --- Official Document System (ODS) ---------------------------------------
ODS_BASE_URL = "https://documents.un.org"
ODS_SYMBOL_ENDPOINT = "/api/symbol/access"
# The six official UN languages. Only "en" has been tested against ODS so far.
ODS_LANGUAGES = frozenset({"ar", "zh", "en", "fr", "ru", "es"})

# --- Politeness limits (Library guidance: max 100 requests per 5 minutes) --
MAX_REQUESTS = 100
WINDOW_SECONDS = 300.0
MIN_INTERVAL_SECONDS = 3.0  # 100 requests per 300 s = one every 3 s

MAX_ATTEMPTS = 3  # tries per request when the server says "slow down" or fails
MAX_RETRY_WAIT_SECONDS = 120.0  # longest we wait inside one call; longer = give up
CONNECT_TIMEOUT_SECONDS = 15.0
READ_TIMEOUT_SECONDS = 60.0
MAX_PDF_BYTES = 50 * 1024 * 1024
