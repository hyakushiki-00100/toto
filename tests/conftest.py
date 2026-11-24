import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BOM = "﻿"


@pytest.fixture
def data(tmp_path):
    """data/ のテンプレートを複製した作業用フォルダ。"""
    d = tmp_path / "data"
    shutil.copytree(ROOT / "data", d)
    return d


def write(path, header, rows):
    lines = [header] + rows
    Path(path).write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")
