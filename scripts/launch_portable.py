"""Start the verified portable build without killing another Agentero session."""

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def running_agentero():
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); Get-CimInstance Win32_Process -Filter \"Name='agentero.exe' OR Name='Agentero-Kaggle.exe'\" | Select-Object -ExpandProperty ProcessId",
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise RuntimeError("无法确认 Agentero 是否已退出，已停止启动。")
    return bool(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-state", type=Path, required=True)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    if running_agentero():
        raise RuntimeError(
            "请先保存工作并完全退出正在运行的 Agentero，再启动 Kaggle 适配版；没有强制关闭任何程序。"
        )
    state = json.loads(args.install_state.read_text(encoding="utf-8"))
    executable = Path(state["executable"]).resolve()
    if (
        hashlib.sha256(executable.read_bytes()).hexdigest()
        != state["executable_sha256"]
    ):
        raise RuntimeError("适配版程序校验未通过，已停止启动。")
    source = Path(os.environ["APPDATA"]) / "agentero"
    folder = args.backup_root / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True, exist_ok=False)
    for name in ("settings.json", "agents.json"):
        path = source / name
        if path.is_file():
            (folder / name).write_bytes(path.read_bytes())
    if args.prepare_only:
        print(
            json.dumps(
                {"executable": str(executable), "backup": str(folder)},
                ensure_ascii=False,
            )
        )
        return
    subprocess.Popen(
        [str(executable)],
        cwd=executable.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("已启动 Agentero Kaggle 适配版。模型仍在云端，使用前请运行 start.bat。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError) as error:
        print("未启动：" + str(error))
        raise SystemExit(1)
