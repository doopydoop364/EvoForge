"""Operator diagnostics. CPU execution is always the training default."""

import importlib.util
import os
import platform
import sys
import tempfile
from pathlib import Path


def diagnose(root="runs"):
    report = {
        "python": platform.python_version(),
        "python_supported": sys.version_info >= (3, 10),
        "cpu_count": os.cpu_count(),
        "execution_default": "cpu",
        "dependencies": {
            name: importlib.util.find_spec(name) is not None
            for name in ("numpy", "torch", "gymnasium", "textual", "fastapi", "uvicorn")
        },
    }
    try:
        path = Path(root).expanduser().resolve()
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path) as file:
            file.write(b"check")
        report["storage_writable"] = True
        from .supervisor import Supervisor

        Supervisor(path)
        report["supervisor_available"] = Path("/proc/sys/kernel/random/boot_id").is_file()
    except (ImportError, OSError, ValueError) as exc:
        report["storage_error"] = str(exc)
        report["supervisor_available"] = False
    try:
        import torch

        report["torch_version"] = torch.__version__
        report["gpu"] = {"available": torch.cuda.is_available(), "kernel_test": "not available"}
        if torch.cuda.is_available():
            report["gpu"].update(
                {
                    "name": torch.cuda.get_device_name(0),
                    "capability": list(torch.cuda.get_device_capability(0)),
                    "compiled_arches": torch.cuda.get_arch_list(),
                }
            )
            try:
                # cuda availability does not establish that SM 6.1 kernels are supported.
                a = torch.ones((8, 8), device="cuda")
                value = (a @ a).sum().item()
                torch.cuda.synchronize()
                report["gpu"]["kernel_test"] = "passed" if value == 512 else "unexpected result"
            except Exception as exc:
                report["gpu"]["kernel_test"] = f"failed: {exc}; use CPU"
        from .sdk.registry import ERRORS, discover

        report["plugins"] = list(discover())
        report["plugin_errors"] = dict(ERRORS)
    except ImportError as exc:
        report["dependency_error"] = str(exc)
    report["api"] = {
        "default_host": "127.0.0.1",
        "token_configured": bool(os.environ.get("EVOFORGE_API_TOKEN")),
        "remote_requires_token": True,
    }
    return report
