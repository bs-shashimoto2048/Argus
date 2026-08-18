from pathlib import Path
import os

ROOT_DIR = Path(__file__).resolve().parents[3]

class Settings:
    app_name = "Argus"
    version = "0.1.0"
    data_dir = Path(os.getenv("ARGUS_DATA_DIR", str(ROOT_DIR / "data"))).resolve()
    database_url = os.getenv("ARGUS_DATABASE_URL", f"sqlite:///{data_dir / 'argus.db'}")
    # Allow only local development origins, regardless of Vite's selected port.
    cors_origins: list[str] = []
    cors_origin_regex = r"^https?://(localhost|127\.0\.0\.1|\[::1\])(?::\d+)?$"

settings = Settings()
