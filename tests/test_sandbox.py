from pathlib import Path

from secure_agents.config import PRESETS
from secure_agents.sandbox import docker_run_args

WS = Path("/tmp/ws-example")


def test_container_is_locked_down_for_every_role():
    for role in ("researcher", "executor"):
        args = docker_run_args(role, WS, PRESETS["full"])
        joined = " ".join(args)
        for flag in ("--network none", "--read-only", "--cap-drop ALL", "no-new-privileges", "--pids-limit", "--memory", "--user 65534:65534"):
            assert flag in joined, (role, flag)


def test_least_privilege_mounts_with_isolation():
    def container_mounts(role):
        # Compare container-side targets only: on macOS /tmp resolves to /private/tmp,
        # so substring checks on the host path would trip on "private".
        args = docker_run_args(role, WS, PRESETS["full"])
        return [args[i + 1].split(":")[1:] for i, a in enumerate(args) if a == "-v"]

    assert container_mounts("researcher") == [["/workspace/docs", "ro"]]
    assert container_mounts("executor") == [["/workspace/notes", "rw"]]


def test_baseline_mounts_everything_writable():
    args = " ".join(docker_run_args("researcher", WS, PRESETS["none"]))
    assert f"{WS}:/workspace:rw" in args and "ROLE_ISOLATION=0" in args


def test_no_api_key_variables_are_passed_to_the_container():
    args = " ".join(docker_run_args("executor", WS, PRESETS["full"]))
    assert "API_KEY" not in args
