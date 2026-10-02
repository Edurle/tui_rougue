"""资源路径解析：兼容开发目录与 PyInstaller 打包后的临时解包目录。"""

import sys
from pathlib import Path


def resource_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative
