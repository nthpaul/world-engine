import importlib.util
from pathlib import Path

import pytest


def test_video_qa_refuses_existing_output_before_any_decoding(tmp_path):
    path = Path(__file__).resolve().parents[1] / "scripts/check_browser_video.py"
    spec = importlib.util.spec_from_file_location("video_qa", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(FileExistsError):
        module.inspect(tmp_path / "missing.webm", tmp_path)
    with pytest.raises(ValueError):
        module.inspect(tmp_path / "missing.webm", tmp_path / "fresh")
