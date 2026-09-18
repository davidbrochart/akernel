import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from akernel.akernel import app


@pytest.mark.parametrize(
    ("options", "name", "interrupt_mode"),
    [
        ([], "akernel", "signal"),
        (["--mode", "process"], "akernel", "signal"),
        (["--mode", "task"], "akernel-task", "message"),
        (["--mode", "thread"], "akernel-thread", "message"),
    ],
)
def test_install_matches_packaged_kernelspec(tmp_path, monkeypatch, options, name, interrupt_mode):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    app(["install", *options], result_action="return_value")
    relative_path = Path("share/jupyter/kernels") / name / "kernel.json"
    installed = json.loads((tmp_path / relative_path).read_text())
    packaged = json.loads((Path(__file__).resolve().parents[1] / relative_path).read_text())
    assert installed == packaged
    assert installed["display_name"] == f"Python 3 ({name})"
    assert installed["interrupt_mode"] == interrupt_mode


def test_install_rejects_unknown_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "prefix", str(tmp_path))
    with pytest.raises(SystemExit) as exc:
        app(["install", "--mode", "unknown"])
    assert exc.value.code != 0
    assert not (tmp_path / "share/jupyter/kernels").exists()


@pytest.mark.parametrize(
    ("module_name", "options", "name", "execute_in_thread"),
    [
        ("AKernelTaskModule", {}, "akernel-task", False),
        ("AKernelTaskModule", {"execute_in_thread": True}, "akernel-thread", True),
        ("AKernelThreadTaskModule", {}, "akernel-thread", True),
    ],
)
async def test_in_process_factory_names(monkeypatch, module_name, options, name, execute_in_thread):
    plugin = pytest.importorskip("fps_akernel_task.main")
    module = getattr(plugin, module_name)("test", **options)
    kernels = Mock()
    monkeypatch.setattr(module, "get", AsyncMock(return_value=kernels))
    await module.prepare()
    kernels.register_kernel_factory.assert_called_once()
    registered_name, factory = kernels.register_kernel_factory.call_args.args
    assert registered_name == name
    assert registered_name != "akernel"
    kernel = factory()
    try:
        assert isinstance(kernel, plugin.AKernelTask)
        assert kernel.execute_in_thread is execute_in_thread
    finally:
        for key, value in vars(kernel).items():
            if key.endswith("_stream") and hasattr(value, "close"):
                value.close()
