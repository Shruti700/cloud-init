# This file is part of cloud-init. See LICENSE file for license information.

import os
from collections import namedtuple

import pytest

import cloudinit.settings
from cloudinit.cmd import clean
from cloudinit.util import ensure_dir, sym_link
from tests.unittests.helpers import mock, wrap_and_call

MyPaths = namedtuple("MyPaths", "cloud_dir")
CleanPaths = namedtuple(
    "CleanPaths", ["tmpdir", "cloud_dir", "clean_dir", "log", "output_log"]
)


@pytest.fixture(scope="function")
def clean_paths(tmpdir):
    return CleanPaths(
        tmpdir=tmpdir,
        cloud_dir=tmpdir.join("varlibcloud"),
        clean_dir=tmpdir.join("clean.d"),
        log=tmpdir.join("cloud-init.log"),
        output_log=tmpdir.join("cloud-init-output.log"),
    )


@pytest.fixture(scope="function")
def init_class(clean_paths):
    class FakeInit:
        cfg = {
            "def_log_file": clean_paths.log,
            "output": {"all": f"|tee -a {clean_paths.output_log}"},
        }
        # Ensure cloud_dir has a trailing slash, to match real behaviour
        paths = MyPaths(cloud_dir=f"{clean_paths.cloud_dir}/")

        def __init__(self, ds_deps):
            pass

        def read_cfg(self):
            pass

    return FakeInit


class TestClean:
    def test_remove_artifacts_removes_logs(self, clean_paths, init_class):
        """remove_artifacts removes logs when remove_logs is True."""
        clean_paths.log.write("cloud-init-log")
        clean_paths.output_log.write("cloud-init-output-log")

        assert (
            os.path.exists(clean_paths.cloud_dir) is False
        ), "Unexpected cloud_dir"
        retcode = wrap_and_call(
            "cloudinit.cmd.clean",
            {"Init": {"side_effect": init_class}},
            clean.remove_artifacts,
            remove_logs=True,
        )
        assert (
            clean_paths.log.exists() is False
        ), f"Unexpected file {clean_paths.log}"
        assert (
            clean_paths.output_log.exists() is False
        ), f"Unexpected file {clean_paths.output_log}"
        assert 0 == retcode

    @pytest.mark.allow_all_subp
    def test_remove_artifacts_runparts_clean_d(self, clean_paths, init_class):
        """remove_artifacts performs runparts on CLEAN_RUNPARTS_DIR"""
        ensure_dir(clean_paths.cloud_dir)
        artifact_file = clean_paths.tmpdir.join("didit")
        ensure_dir(clean_paths.clean_dir)
        assert artifact_file.exists() is False, f"Unexpected {artifact_file}"
        clean_script = clean_paths.clean_dir.join("1.sh")
        clean_script.write(f"#!/bin/sh\ntouch {artifact_file}\n")
        clean_script.chmod(mode=0o755)
        with mock.patch.object(
            cloudinit.settings, "CLEAN_RUNPARTS_DIR", clean_paths.clean_dir
        ):
            retcode = wrap_and_call(
                "cloudinit.cmd.clean",
                {
                    "Init": {"side_effect": init_class},
                },
                clean.remove_artifacts,
                remove_logs=False,
            )
        assert (
            artifact_file.exists() is True
        ), f"Missing expected {artifact_file}"
        assert 0 == retcode

    def test_remove_artifacts_preserves_logs(self, clean_paths, init_class):
        """remove_artifacts leaves logs when remove_logs is False."""
        clean_paths.log.write("cloud-init-log")
        clean_paths.output_log.write("cloud-init-output-log")

        retcode = wrap_and_call(
            "cloudinit.cmd.clean",
            {"Init": {"side_effect": init_class}},
            clean.remove_artifacts,
            remove_logs=False,
        )
        assert 0 == retcode
        assert (
            clean_paths.log.exists() is True
        ), f"Missing expected file {clean_paths.log}"
        assert (
            clean_paths.output_log.exists()
        ), f"Missing expected file {clean_paths.output_log}"

    def test_remove_artifacts_removes_unlinks_symlinks(
        self, clean_paths, init_class
    ):
        """remove_artifacts cleans artifacts dir unlinking any symlinks."""
        dir1 = clean_paths.cloud_dir.join("dir1")
        ensure_dir(dir1)
        symlink = clean_paths.cloud_dir.join("mylink")
        sym_link(dir1.strpath, symlink.strpath)

        with mock.patch.object(
            cloudinit.settings, "CLEAN_RUNPARTS_DIR", clean_paths.clean_dir
        ):
            retcode = wrap_and_call(
                "cloudinit.cmd.clean",
                {"Init": {"side_effect": init_class}},
                clean.remove_artifacts,
                remove_logs=False,
            )
        assert 0 == retcode
        for path in (dir1, symlink):
            assert path.exists() is False, f"Unexpected {path} found"

    def test_remove_artifacts_removes_artifacts_skipping_seed(
        self, clean_paths, init_class
    ):
        """remove_artifacts cleans artifacts dir with exception of seed dir."""
        dirs = [
            clean_paths.cloud_dir,
            clean_paths.cloud_dir.join("seed"),
            clean_paths.cloud_dir.join("dir1"),
            clean_paths.cloud_dir.join("dir2"),
        ]
        for _dir in dirs:
            ensure_dir(_dir)

        with mock.patch.object(
            cloudinit.settings, "CLEAN_RUNPARTS_DIR", clean_paths.clean_dir
        ):
            retcode = wrap_and_call(
                "cloudinit.cmd.clean",
                {"Init": {"side_effect": init_class}},
                clean.remove_artifacts,
                remove_logs=False,
            )
        assert 0 == retcode
        for expected_dir in dirs[:2]:
            assert expected_dir.exists() is True, f"Missing {expected_dir}"
        for deleted_dir in dirs[2:]:
            assert deleted_dir.exists() is False, f"Unexpected {deleted_dir}"

    def test_remove_artifacts_removes_artifacts_removes_seed(
        self, clean_paths, init_class
    ):
        """remove_artifacts removes seed dir when remove_seed is True."""
        dirs = [
            clean_paths.cloud_dir,
            clean_paths.cloud_dir.join("seed"),
            clean_paths.cloud_dir.join("dir1"),
            clean_paths.cloud_dir.join("dir2"),
        ]
        for _dir in dirs:
            ensure_dir(_dir)

        with mock.patch.object(
            cloudinit.settings, "CLEAN_RUNPARTS_DIR", clean_paths.clean_dir
        ):
            retcode = wrap_and_call(
                "cloudinit.cmd.clean",
                {"Init": {"side_effect": init_class}},
                clean.remove_artifacts,
                remove_logs=False,
                remove_seed=True,
            )
        assert 0 == retcode
        assert (
            clean_paths.cloud_dir.exists() is True
        ), f"Missing dir {clean_paths.cloud_dir}"
        for deleted_dir in dirs[1:]:
            assert (
                deleted_dir.exists() is False
            ), f"Unexpected {deleted_dir} dir"

    def test_remove_artifacts_returns_one_on_errors(
        self, clean_paths, init_class, capsys
    ):
        """remove_artifacts returns non-zero on failure and prints an error."""
        ensure_dir(clean_paths.cloud_dir)
        ensure_dir(clean_paths.cloud_dir.join("dir1"))

        retcode = wrap_and_call(
            "cloudinit.cmd.clean",
            {
                "del_dir": {"side_effect": OSError("oops")},
                "Init": {"side_effect": init_class},
            },
            clean.remove_artifacts,
            remove_logs=False,
        )
        assert 1 == retcode
        _out, err = capsys.readouterr()
        assert (
            f"Error:\nCould not remove {clean_paths.cloud_dir}/dir1: oops\n"
            == err
        )

    def test_handle_clean_args_reboots(self, init_class):
        """handle_clean_args_reboots when reboot arg is provided."""

        called_cmds = []

        def fake_subp(cmd, capture):
            called_cmds.append((cmd, capture))
            return "", ""

        myargs = namedtuple(
            "MyArgs", "remove_logs remove_seed reboot machine_id"
        )
        cmdargs = myargs(
            remove_logs=False, remove_seed=False, reboot=True, machine_id=False
        )
        retcode = wrap_and_call(
            "cloudinit.cmd.clean",
            {
                "subp": {"side_effect": fake_subp},
                "Init": {"side_effect": init_class},
            },
            clean.handle_clean_args,
            name="does not matter",
            args=cmdargs,
        )
        assert 0 == retcode
        assert [(["shutdown", "-r", "now"], False)] == called_cmds

    @pytest.mark.parametrize(
        "machine_id,systemd_val",
        (
            pytest.param(True, True, id="machine_id_on_systemd_uninitialized"),
            pytest.param(
                True, False, id="machine_id_non_systemd_removes_file"
            ),
            pytest.param(False, False, id="no_machine_id_param_file_remains"),
        ),
    )
    @mock.patch("cloudinit.cmd.clean.uses_systemd")
    def test_handle_clean_args_removed_machine_id(
        self, uses_systemd, machine_id, systemd_val, clean_paths, init_class
    ):
        """handle_clean_args removes /etc/machine-id when arg is True."""
        uses_systemd.return_value = systemd_val
        myargs = namedtuple(
            "MyArgs", "remove_logs remove_seed reboot machine_id"
        )
        cmdargs = myargs(
            remove_logs=False,
            remove_seed=False,
            reboot=False,
            machine_id=machine_id,
        )
        machine_id_path = clean_paths.tmpdir.join("machine-id")
        machine_id_path.write("SOME-AMAZN-MACHINE-ID")
        with mock.patch.object(
            cloudinit.settings, "CLEAN_RUNPARTS_DIR", clean_paths.clean_dir
        ):
            with mock.patch.object(
                cloudinit.cmd.clean, "ETC_MACHINE_ID", machine_id_path.strpath
            ):
                retcode = wrap_and_call(
                    "cloudinit.cmd.clean",
                    {
                        "Init": {"side_effect": init_class},
                    },
                    clean.handle_clean_args,
                    name="does not matter",
                    args=cmdargs,
                )
        assert 0 == retcode
        if systemd_val:
            if machine_id:
                assert "uninitialized\n" == machine_id_path.read()
            else:
                assert "SOME-AMAZN-MACHINE-ID" == machine_id_path.read()
        else:
            assert machine_id_path.exists() is bool(not machine_id)

    def test_status_main(self, clean_paths, init_class):
        """clean.main can be run as a standalone script."""
        clean_paths.log.write("cloud-init-log")
        with pytest.raises(SystemExit) as context_manager:
            wrap_and_call(
                "cloudinit.cmd.clean",
                {
                    "Init": {"side_effect": init_class},
                    "sys.argv": {"new": ["clean", "--logs"]},
                },
                clean.main,
            )
        assert 0 == context_manager.value.code
        assert (
            clean_paths.log.exists() is False
        ), f"Unexpected log {clean_paths.log}"


# vi: ts=4 expandtab syntax=python
