import sys
from unittest.mock import patch, MagicMock
import pytest
from agentscope.cli import find_repo_paths, main

def test_find_repo_paths():
    """Verify that find_repo_paths executes without crashing and returns either paths or None."""
    root, server, ui, docker_compose = find_repo_paths()
    # Should be tuple of 4 elements
    assert len((root, server, ui, docker_compose)) == 4

@patch("agentscope.cli.find_repo_paths")
@patch("argparse.ArgumentParser.parse_args")
def test_cli_main_start_docker(mock_parse_args, mock_find_paths):
    """Test that running 'agentscope start --docker' invokes docker compose command."""
    mock_args = MagicMock()
    mock_args.command = "start"
    mock_args.docker = True
    mock_args.host = "127.0.0.1"
    mock_args.port = 8765
    mock_args.ui_port = 3000
    mock_parse_args.return_value = mock_args

    mock_find_paths.return_value = ("/root", "/root/packages/server", "/root/packages/ui", "/root/docker-compose.yml")

    with patch("shutil.which", return_value="/usr/bin/docker"), \
         patch("os.path.exists", return_value=True), \
         patch("subprocess.run") as mock_run:
        
        main()
        mock_run.assert_any_call(["docker", "compose", "up", "--build"], cwd="/root", check=True)

@patch("agentscope.cli.find_repo_paths")
@patch("argparse.ArgumentParser.parse_args")
def test_cli_main_start_local(mock_parse_args, mock_find_paths):
    """Test that running 'agentscope start' spawns local uvicorn and next.js processes."""
    mock_args = MagicMock()
    mock_args.command = "start"
    mock_args.docker = False
    mock_args.host = "127.0.0.1"
    mock_args.port = 8765
    mock_args.ui_port = 3000
    mock_parse_args.return_value = mock_args

    mock_find_paths.return_value = ("/root", "/root/packages/server", "/root/packages/ui", "/root/docker-compose.yml")

    # Mock sys.modules['uvicorn'] to bypass ImportError
    sys.modules['uvicorn'] = MagicMock()

    with patch("shutil.which", return_value="/usr/bin/npm"), \
         patch("os.path.exists", return_value=True), \
         patch("subprocess.Popen") as mock_popen, \
         patch("time.sleep") as mock_sleep:
        
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
