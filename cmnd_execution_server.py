"""
Cmnd Execution MCP Server (full-fledged)
-----------------------------------------
A local MCP server that lets Claude (or any MCP client) execute
commands and inspect this machine, similar in spirit to your
file_handeling_server but for command execution / system control.

Install:
    pip install mcp psutil

Run:
    python cmnd_execution_server.py

Then add it to your MCP client config the same way you added
file_handeling_server, pointing at this script.
"""

import subprocess
import os
import platform
import shutil
from datetime import datetime
from mcp.server.fastmcp import FastMCP

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

mcp = FastMCP("cmnd_execution_server")

# ---------------------------------------------------------------------------
# SAFETY CONFIG - edit before relying on this daily
# ---------------------------------------------------------------------------

BLOCKED_PATTERNS = [
    "rm -rf",
    "del /f",
    "del /s",
    "format ",
    "shutdown",
    "diskpart",
    "mkfs",
    "reg delete",
    "reg add",
    "net user",
    "taskkill /f /im",
    ":(){ :|:& };:",  # fork bomb
]

# Confine commands to a folder. None = unrestricted.
DEFAULT_WORKDIR = None  # e.g. r"C:\Users\gunta\Downloads"

DEFAULT_TIMEOUT = 30  # seconds

LOG_FILE = os.path.join(os.path.dirname(__file__), "command_log.txt")

# Processes you never want killable via kill_process, even if PID matches.
PROTECTED_PROCESS_NAMES = {"explorer.exe", "System", "csrss.exe", "wininit.exe"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_blocked(command: str) -> bool:
    lowered = command.lower()
    return any(pattern.lower() in lowered for pattern in BLOCKED_PATTERNS)


def _log(entry: str):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now().isoformat()}] {entry}\n")


def _build_shell_command(command: str, shell_type: str) -> list:
    """Wrap the command for cmd.exe, PowerShell, or run as-is."""
    shell_type = (shell_type or "cmd").lower()
    if shell_type == "powershell":
        return ["powershell", "-NoProfile", "-Command", command]
    elif shell_type == "cmd":
        return ["cmd", "/c", command]
    elif shell_type == "raw":
        return command  # let subprocess use shell=True directly
    else:
        raise ValueError("shell_type must be 'cmd', 'powershell', or 'raw'")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def run_command(command: str, cwd: str = None, timeout_seconds: int = None,
                 shell_type: str = "cmd") -> dict:
    """
    Run a command in Command Prompt or PowerShell and return the output.

    Args:
        command: The command to run, e.g. "npm install" or "Get-Process".
        cwd: Optional working directory.
        timeout_seconds: Kill the command if it runs longer than this (default 30s).
        shell_type: "cmd" (default), "powershell", or "raw" (uses shell=True directly).
    """
    if _is_blocked(command):
        return {"command": command, "stdout": "", "stderr": "Blocked: disallowed pattern.", "exit_code": -1}

    workdir = cwd or DEFAULT_WORKDIR or os.getcwd()
    timeout = timeout_seconds or DEFAULT_TIMEOUT

    try:
        shell_cmd = _build_shell_command(command, shell_type)
        use_shell = shell_type == "raw"
        result = subprocess.run(
            shell_cmd,
            shell=use_shell,
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        _log(f"[{shell_type}] cwd={workdir} exit={result.returncode} :: {command}")
        return {
            "command": command,
            "shell_type": shell_type,
            "cwd": workdir,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        _log(f"[{shell_type}] cwd={workdir} exit=TIMEOUT :: {command}")
        return {"command": command, "cwd": workdir, "stdout": "",
                 "stderr": f"Timed out after {timeout}s.", "exit_code": -2}
    except Exception as e:
        _log(f"[{shell_type}] cwd={workdir} exit=ERROR :: {command} -> {e}")
        return {"command": command, "cwd": workdir, "stdout": "",
                 "stderr": f"Failed to run: {e}", "exit_code": -3}


@mcp.tool()
def run_python_code(code: str, timeout_seconds: int = None) -> dict:
    """
    Run a snippet of Python code on this machine using the local
    Python interpreter and return stdout/stderr.

    Args:
        code: Python source code to execute.
        timeout_seconds: Kill if it runs longer than this (default 30s).
    """
    timeout = timeout_seconds or DEFAULT_TIMEOUT
    try:
        result = subprocess.run(
            ["python", "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        _log(f"[python] exit={result.returncode} :: {code[:80]}")
        return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": f"Timed out after {timeout}s.", "exit_code": -2}
    except Exception as e:
        return {"stdout": "", "stderr": f"Failed to run: {e}", "exit_code": -3}


@mcp.tool()
def get_command_log(last_n: int = 20) -> str:
    """Return the last N lines of the command audit log."""
    if not os.path.exists(LOG_FILE):
        return "No commands logged yet."
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[-last_n:]) if lines else "Log file is empty."


@mcp.tool()
def get_system_info() -> dict:
    """Return basic system info: OS, machine, processor, Python version, disk usage."""
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "cwd": os.getcwd(),
    }
    try:
        total, used, free = shutil.disk_usage(os.path.abspath(os.sep))
        info["disk_total_gb"] = round(total / (1024**3), 2)
        info["disk_used_gb"] = round(used / (1024**3), 2)
        info["disk_free_gb"] = round(free / (1024**3), 2)
    except Exception:
        pass
    if HAS_PSUTIL:
        info["cpu_percent"] = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        info["memory_total_gb"] = round(mem.total / (1024**3), 2)
        info["memory_used_percent"] = mem.percent
    else:
        info["note"] = "Install psutil for CPU/memory stats: pip install psutil"
    return info


@mcp.tool()
def list_processes(name_filter: str = None) -> list:
    """
    List running processes (requires psutil).

    Args:
        name_filter: Optional substring to filter process names by.
    """
    if not HAS_PSUTIL:
        return [{"error": "psutil not installed. Run: pip install psutil"}]
    procs = []
    for p in psutil.process_iter(["pid", "name", "memory_percent", "cpu_percent"]):
        try:
            info = p.info
            if name_filter and name_filter.lower() not in (info["name"] or "").lower():
                continue
            procs.append({
                "pid": info["pid"],
                "name": info["name"],
                "memory_percent": round(info["memory_percent"], 2) if info["memory_percent"] else 0,
                "cpu_percent": info["cpu_percent"],
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs[:200]  # cap output


@mcp.tool()
def kill_process(pid: int) -> dict:
    """
    Kill a process by PID (requires psutil). Refuses to kill protected
    system processes.

    Args:
        pid: Process ID to terminate.
    """
    if not HAS_PSUTIL:
        return {"error": "psutil not installed. Run: pip install psutil"}
    try:
        p = psutil.Process(pid)
        if p.name() in PROTECTED_PROCESS_NAMES:
            return {"error": f"Refusing to kill protected process: {p.name()}"}
        p.terminate()
        _log(f"[kill_process] pid={pid} name={p.name()}")
        return {"status": "terminated", "pid": pid, "name": p.name()}
    except psutil.NoSuchProcess:
        return {"error": f"No process with PID {pid}"}
    except psutil.AccessDenied:
        return {"error": f"Access denied trying to kill PID {pid}. Try running as admin."}


@mcp.tool()
def get_env_var(name: str) -> str:
    """Get the value of an environment variable."""
    return os.environ.get(name, f"'{name}' is not set.")


@mcp.tool()
def list_env_vars(filter_prefix: str = None) -> dict:
    """
    List environment variables.

    Args:
        filter_prefix: Optional prefix to filter var names by (e.g. "PATH").
    """
    if filter_prefix:
        return {k: v for k, v in os.environ.items() if k.upper().startswith(filter_prefix.upper())}
    return dict(os.environ)


@mcp.tool()
def get_current_directory() -> str:
    """Return the current working directory of this MCP server process."""
    return os.getcwd()


if __name__ == "__main__":
    mcp.run()
