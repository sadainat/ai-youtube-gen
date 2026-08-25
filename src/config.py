"""Shared project paths and environment loading."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


REQUIRE_REAL_VIDEO = env_flag("REQUIRE_REAL_VIDEO", default=True)
REQUIRE_FACEBOOK_UPLOAD = env_flag("REQUIRE_FACEBOOK_UPLOAD", default=True)
