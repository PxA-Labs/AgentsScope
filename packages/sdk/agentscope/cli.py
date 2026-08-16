#!/usr/bin/env python3
import argparse
import os
import sys
import subprocess
import threading
import shutil
import time

def log_reader(pipe, prefix):
    """Reads lines from a subprocess pipe and prints them with a prefix."""
    try:
        for line in pipe:
            print(f"{prefix} {line.strip()}", flush=True)
    except Exception:
        pass
    finally:
        try:
            pipe.close()
        except Exception:
            pass

def find_repo_paths():
    """Finds the paths to the server and UI directories."""
    # 1. Check relative to this script's file location (monorepo structure)
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_root = os.path.abspath(os.path.join(script_dir, "..", "..", ".."))
        server_dir = os.path.join(repo_root, "packages", "server")
        ui_dir = os.path.join(repo_root, "packages", "ui")
        docker_compose = os.path.join(repo_root, "docker-compose.yml")
        
        if os.path.exists(os.path.join(server_dir, "main.py")) and os.path.exists(ui_dir):
            return repo_root, server_dir, ui_dir, docker_compose
    except Exception:
        pass

    # 2. Check relative to current working directory
    cwd = os.getcwd()
    server_dir = os.path.join(cwd, "packages", "server")
    ui_dir = os.path.join(cwd, "packages", "ui")
    docker_compose = os.path.join(cwd, "docker-compose.yml")
    if os.path.exists(os.path.join(server_dir, "main.py")) and os.path.exists(ui_dir):
        return cwd, server_dir, ui_dir, docker_compose

    return None, None, None, None

def run_docker(docker_compose_path):
    """Runs the services using Docker Compose."""
    if not shutil.which("docker"):
        print("Error: 'docker' command is not available. Please install Docker.", file=sys.stderr)
        sys.exit(1)
        
    cmd = ["docker", "compose", "up", "--build"]
    print(f"[*] Starting AgentScope services via Docker Compose...")
    print(f"[*] Command: {' '.join(cmd)}")
    
    cwd = os.path.dirname(docker_compose_path)
    try:
        subprocess.run(cmd, cwd=cwd, check=True)
    except KeyboardInterrupt:
        print("\n[*] Stopping Docker containers...")
        subprocess.run(["docker", "compose", "down"], cwd=cwd)
    except subprocess.CalledProcessError as e:
        print(f"Error: Docker Compose failed with exit code {e.returncode}", file=sys.stderr)
        sys.exit(1)

def run_local(server_dir, ui_dir, host, port, ui_port):
    """Runs the services locally using Python and Node.js subprocesses."""
    # Check for python dependencies
    # We need uvicorn to run the FastAPI app
    try:
        import uvicorn
    except ImportError:
        print("Error: 'uvicorn' is not installed in the current environment.", file=sys.stderr)
        print("Please install it with: pip install uvicorn", file=sys.stderr)
        sys.exit(1)

    # Check if npm is installed for UI
    if not shutil.which("npm"):
        print("Error: 'npm' command is not found. Node.js/npm is required to run the UI locally.", file=sys.stderr)
        sys.exit(1)

    # Check if UI node_modules are installed
    if not os.path.exists(os.path.join(ui_dir, "node_modules")):
        print(f"[*] node_modules not found in {ui_dir}. Running 'npm install'...")
        try:
            # We use --legacy-peer-deps to avoid peer dependency conflicts
            subprocess.run(["npm", "install", "--legacy-peer-deps"], cwd=ui_dir, check=True)
        except subprocess.CalledProcessError as e:
            print(f"Error: 'npm install' failed with exit code {e.returncode}", file=sys.stderr)
            sys.exit(1)

    # Define color prefixes for console output
    backend_prefix = "\033[36m[Backend]\033[0m"
    backend_err_prefix = "\033[31m[Backend-Err]\033[0m"
    ui_prefix = "\033[35m[UI]\033[0m"
    ui_err_prefix = "\033[31m[UI-Err]\033[0m"

    print("=" * 70)
    print("                 Welcome to AgentScope Observability")
    print("=" * 70)
    print(f"[+] Observability Server starting on: http://{host}:{port}")
    print(f"[+] Developer Dashboard starting on:  http://localhost:{ui_port}")
    print("[+] Press Ctrl+C to stop all services.")
    print("=" * 70)
    print("[*] Starting backend and frontend processes...")

    # Environment variables overrides for UI client endpoints
    ui_env = os.environ.copy()
    ui_env["NEXT_PUBLIC_API_URL"] = f"http://{host}:{port}"
    ui_env["NEXT_PUBLIC_WS_URL"] = f"ws://{host}:{port}"

    # Start Backend Server
    server_cmd = [sys.executable, "-m", "uvicorn", "main:app", "--host", host, "--port", str(port)]
    p_server = subprocess.Popen(
        server_cmd,
        cwd=server_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    # Start UI Frontend
    ui_cmd = ["npm", "run", "dev", "--", "-p", str(ui_port)]
    p_ui = subprocess.Popen(
        ui_cmd,
        cwd=ui_dir,
        env=ui_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    threads = []
    # Start log readers
    t_server_out = threading.Thread(target=log_reader, args=(p_server.stdout, backend_prefix), daemon=True)
    t_server_err = threading.Thread(target=log_reader, args=(p_server.stderr, backend_err_prefix), daemon=True)
    t_ui_out = threading.Thread(target=log_reader, args=(p_ui.stdout, ui_prefix), daemon=True)
    t_ui_err = threading.Thread(target=log_reader, args=(p_ui.stderr, ui_err_prefix), daemon=True)

    for t in [t_server_out, t_server_err, t_ui_out, t_ui_err]:
        t.start()
        threads.append(t)

    try:
        # Keep main thread alive while subprocesses are running
        while True:
            # Check if any process exited early (crashed)
            server_exit = p_server.poll()
            ui_exit = p_ui.poll()

            if server_exit is not None:
                print(f"Error: Backend server exited unexpectedly with code {server_exit}", file=sys.stderr)
                break
            if ui_exit is not None:
                print(f"Error: UI server exited unexpectedly with code {ui_exit}", file=sys.stderr)
                break
            
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[*] Stopping AgentScope services...")
    finally:
        # Graceful shutdown of subprocesses
        p_server.terminate()
        p_ui.terminate()

        # Wait up to 3 seconds for graceful exit
        for _ in range(30):
            if p_server.poll() is not None and p_ui.poll() is not None:
                break
            time.sleep(0.1)

        # Force kill if still running
        if p_server.poll() is None:
            p_server.kill()
        if p_ui.poll() is None:
            p_ui.kill()

        print("[*] Services stopped successfully.")

def main():
    parser = argparse.ArgumentParser(
        description="AgentScope CLI: Observability suite management."
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # Start command parser
    start_parser = subparsers.add_parser("start", help="Start AgentScope services")
    start_parser.add_argument(
        "--host", 
        default="127.0.0.1", 
        help="Host address for the FastAPI backend (default: 127.0.0.1)"
    )
    start_parser.add_argument(
        "--port", 
        type=int, 
        default=8765, 
        help="Port for the FastAPI backend (default: 8765)"
    )
    start_parser.add_argument(
        "--ui-port", 
        type=int, 
        default=3000, 
        help="Port for the Next.js UI dashboard (default: 3000)"
    )
    start_parser.add_argument(
        "--docker", 
        action="store_true", 
        help="Run using Docker Compose instead of local Python/Node.js"
    )

    args = parser.parse_args()

    if args.command == "start":
        repo_root, server_dir, ui_dir, docker_compose = find_repo_paths()

        if args.docker:
            if docker_compose and os.path.exists(docker_compose):
                run_docker(docker_compose)
            else:
                # Try finding docker-compose in current directory
                cwd = os.getcwd()
                local_dc = os.path.join(cwd, "docker-compose.yml")
                if os.path.exists(local_dc):
                    run_docker(local_dc)
                else:
                    print("Error: Could not find docker-compose.yml file.", file=sys.stderr)
                    sys.exit(1)
        else:
            if server_dir and ui_dir:
                run_local(server_dir, ui_dir, args.host, args.port, args.ui_port)
            else:
                print("Error: Could not locate 'packages/server' and 'packages/ui' directories.", file=sys.stderr)
                print("Please ensure you run this command from the repository root or a valid monorepo path.", file=sys.stderr)
                sys.exit(1)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
