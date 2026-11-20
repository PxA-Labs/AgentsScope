from unittest.mock import MagicMock, patch

import pytest

from agentscope_trace.cli import find_repo_paths, main


def test_find_repo_paths():
    """Verify that find_repo_paths executes and returns either paths or None."""
    root, server, ui, docker_compose = find_repo_paths()
    # Should be tuple of 4 elements
    assert len((root, server, ui, docker_compose)) == 4


@patch("agentscope_trace.cli.find_repo_paths")
@patch("argparse.ArgumentParser.parse_args")
def test_cli_main_start_docker(mock_parse_args, mock_find_paths):
    """Test that running 'agentscope start --docker' invokes docker compose."""
    mock_args = MagicMock()
    mock_args.command = "start"
    mock_args.docker = True
    mock_args.host = "127.0.0.1"
    mock_args.port = 8765
    mock_args.ui_port = 3000
    mock_parse_args.return_value = mock_args

    mock_find_paths.return_value = (
        "/root",
        "/root/packages/server",
        "/root/packages/ui",
        "/root/docker-compose.yml",
    )

    with (
        patch("shutil.which", return_value="/usr/bin/docker"),
        patch("os.path.exists", return_value=True),
        patch("subprocess.run") as mock_run,
    ):

        main()
        mock_run.assert_any_call(
            ["docker", "compose", "up", "--build"], cwd="/root", check=True
        )


@patch("agentscope_trace.cli.find_repo_paths")
@patch("argparse.ArgumentParser.parse_args")
def test_cli_main_start_local(mock_parse_args, mock_find_paths):
    """Test that running 'agentscope start' spawns local processes."""
    mock_args = MagicMock()
    mock_args.command = "start"
    mock_args.docker = False
    mock_args.host = "127.0.0.1"
    mock_args.port = 8765
    mock_args.ui_port = 3000
    mock_parse_args.return_value = mock_args

    mock_find_paths.return_value = (
        "/root",
        "/root/packages/server",
        "/root/packages/ui",
        "/root/docker-compose.yml",
    )

    with (
        patch.dict("sys.modules", {"uvicorn": MagicMock()}),
        patch("shutil.which", return_value="/usr/bin/npm"),
        patch("os.path.exists", return_value=True),
        patch("subprocess.Popen") as mock_popen,
        patch("time.sleep"),
    ):

        # Mock subprocess instances returning from Popen
        mock_proc_server = MagicMock()
        mock_proc_ui = MagicMock()
        mock_proc_server.poll.return_value = 0  # server exited, breaks loop immediately
        mock_proc_ui.poll.return_value = None
        mock_popen.side_effect = [mock_proc_server, mock_proc_ui]

        main()

        # Popen should have been called twice (once for server, once for ui)
        assert mock_popen.call_count == 2

        # Verify terminate was called on both processes during cleanup
        mock_proc_server.terminate.assert_called_once()
        mock_proc_ui.terminate.assert_called_once()


def _run_main(argv, monkeypatch, tmp_path):
    monkeypatch.setattr("sys.argv", ["agentscope", *argv])
    monkeypatch.chdir(tmp_path)  # not a repository checkout
    monkeypatch.setattr(
        "agentscope_trace.cli.find_repo_paths", lambda: (None, None, None, None)
    )
    main()


@pytest.mark.parametrize("argv", [["start"], ["start", "--docker"]])
def test_start_outside_checkout_explains_what_to_do(
    argv, monkeypatch, tmp_path, capsys
):
    with pytest.raises(SystemExit) as exc:
        _run_main(argv, monkeypatch, tmp_path)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "git clone https://github.com/PxA-Labs/AgentsScope.git" in err
    assert "agentscope-trace" in err


def test_version_flag(monkeypatch, tmp_path, capsys):
    from agentscope_trace import __version__

    with pytest.raises(SystemExit) as exc:
        _run_main(["--version"], monkeypatch, tmp_path)
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"agentscope-trace {__version__}"
