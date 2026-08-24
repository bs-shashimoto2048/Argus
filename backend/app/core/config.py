from pathlib import Path
import os

ROOT_DIR = Path(__file__).resolve().parents[3]

class Settings:
    app_name = "Argus"
    version = "0.1.0"
    data_dir = Path(os.getenv("ARGUS_DATA_DIR", str(ROOT_DIR / "data"))).resolve()
    database_url = os.getenv("ARGUS_DATABASE_URL", f"sqlite:///{data_dir / 'argus.db'}")
    # Allow only local development origins, regardless of Vite's selected port.
    # Issue #26 (LAN access from another in-office PC): this intentionally does
    # NOT include LAN origins. LAN clients are expected to go through the
    # Frontend's same-origin Vite proxy (relative /api/** calls), which browsers
    # never treat as cross-origin, so CORS is not consulted for that path at
    # all. This regex only matters if something tries to call the Backend
    # directly from a browser; since the Backend binds to 127.0.0.1 only, that
    # is not reachable from the LAN in the first place. Do not widen this to
    # accept LAN origins as a way to "support" direct Backend access from the
    # LAN — keep the Backend loopback-only instead.
    cors_origins: list[str] = []
    cors_origin_regex = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$"

settings = Settings()
