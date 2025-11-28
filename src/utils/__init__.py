from .config import load_config
from models import TrendRadarConfig
from .datetime import get_beijing_time
from .version import check_version_update
from .path import ensure_directory_exists, get_output_path

__all__ = ["get_beijing_time", "check_version_update", "ensure_directory_exists", "get_output_path"]

CONFIG: TrendRadarConfig = load_config()
VERSION: str = "3.3.0"
