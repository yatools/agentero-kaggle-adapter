"""Exercise delivery with tiny synthetic archives; no network or executable launch."""

import hashlib
import contextlib
import io
import importlib.util
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "scripts" / (name + ".py")
    )
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


install = module("install_portable")
launch = module("launch_portable")


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        scratch = (ROOT / ".work/tests").resolve()
        assert scratch.is_relative_to(ROOT.resolve())
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "deployment").mkdir()
        self.downloads = self.root / "AgenteroKaggleAdapter/.work/download"
        self.downloads.mkdir(parents=True)
        self.patch = self.root / "AgenteroKaggleAdapter/patches/agentero.patch"
        self.patch.parent.mkdir()
        self.patch.write_bytes(b"synthetic adaptation patch")

    def archive(self, extra=None, corrupt=False):
        files = {
            "agentero.exe": b"synthetic-not-executable",
            "pdfium/test.dll": b"synthetic-resource",
        }
        manifest = {
            "upstream_commit": "fdacc2bc9da8a4e5569cf986acf2ef09e62d396b",
            "patch_sha256": hashlib.sha256(self.patch.read_bytes()).hexdigest(),
            "profile": {
                "batch_size": 32,
                "highlight_concurrency": 1,
                "request_timeout_seconds": 300,
            },
            "model_weights_included": False,
            "files": {
                name: hashlib.sha256(data).hexdigest() for name, data in files.items()
            },
        }
        if corrupt:
            manifest["files"]["agentero.exe"] = "0" * 64
        archive = self.downloads / "Agentero-Kaggle-v1-windows-x64.zip"
        with zipfile.ZipFile(archive, "w") as handle:
            for name, data in files.items():
                handle.writestr("Agentero-Kaggle-v1/" + name, data)
            handle.writestr(
                "Agentero-Kaggle-v1/BUILD-MANIFEST.json", json.dumps(manifest)
            )
            if extra:
                handle.writestr(extra, b"synthetic test data")
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        (self.downloads / "SHA256SUMS.txt").write_text(digest + "  " + archive.name)
        return archive

    def run_install(self):
        with (
            patch.object(sys, "argv", ["install", "--workspace", str(self.root)]),
            patch.object(install, "download_assets") as command,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                install.main()
        command.assert_called_once_with(self.downloads, "gh")

    def test_verified_package_installs_in_a_versioned_directory(self):
        self.archive()
        self.run_install()
        state = json.loads((self.root / "deployment/portable-install.json").read_text())
        executable = Path(state["executable"])
        self.assertTrue(executable.is_relative_to(self.root / "Agentero-Kaggle"))
        self.assertEqual(executable.read_bytes(), b"synthetic-not-executable")
        self.assertEqual(state["local_model_download_bytes"], 0)

    def test_path_traversal_is_rejected_before_outside_write(self):
        self.archive(extra="Agentero-Kaggle-v1/../../escape.txt")
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertFalse((self.root / "deployment/portable-install.json").exists())

    def test_model_file_is_rejected_without_extraction(self):
        self.archive(extra="Agentero-Kaggle-v1/not-a-real-model.gguf")
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertFalse(list((self.root / "Agentero-Kaggle").rglob("*.gguf")))

    def test_corrupted_resource_cannot_be_marked_installed(self):
        self.archive(corrupt=True)
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertFalse((self.root / "deployment/portable-install.json").exists())

    def test_archive_checksum_mismatch_stops_installation(self):
        self.archive()
        (self.downloads / "SHA256SUMS.txt").write_text("0" * 64 + " archive.zip")
        with self.assertRaises(RuntimeError):
            self.run_install()
        self.assertFalse((self.root / "Agentero-Kaggle").exists())

    def test_running_original_is_never_terminated(self):
        with (
            patch.object(
                sys,
                "argv",
                [
                    "launch",
                    "--install-state",
                    str(self.root / "unused.json"),
                    "--backup-root",
                    str(self.root / "backup"),
                ],
            ),
            patch.object(launch, "running_agentero", return_value=True),
            patch.object(launch.subprocess, "Popen") as spawn,
        ):
            with self.assertRaises(RuntimeError):
                launch.main()
        spawn.assert_not_called()
        self.assertFalse((self.root / "backup").exists())

    def test_launch_backs_up_private_settings_locally(self):
        self.archive()
        self.run_install()
        profile = self.root / "private-appdata/agentero"
        profile.mkdir(parents=True)
        (profile / "settings.json").write_text('{"key":"synthetic-only"}')
        (profile / "agents.json").write_text("[]")
        with (
            patch.object(
                sys,
                "argv",
                [
                    "launch",
                    "--install-state",
                    str(self.root / "deployment/portable-install.json"),
                    "--backup-root",
                    str(self.root / "backup"),
                ],
            ),
            patch.object(launch, "running_agentero", return_value=False),
            patch.dict(os.environ, {"APPDATA": str(profile.parent)}),
            patch.object(launch.subprocess, "Popen") as spawn,
        ):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                launch.main()
            self.assertNotIn("synthetic-only", output.getvalue())
        spawn.assert_called_once()
        backups = list((self.root / "backup").glob("*/settings.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(
            backups[0].read_text(), (profile / "settings.json").read_text()
        )


if __name__ == "__main__":
    unittest.main()
