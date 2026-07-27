"""Phase: path_traversal — _activate_path_traversal and _path_traversal_tools."""

from __future__ import annotations

import logging
from typing import Any

from ._types import ToolTask, _get_attr, _get_tech_stack

logger = logging.getLogger(__name__)





# File access functions and path-related keywords by language
_FILE_ACCESS_FUNCTIONS: set[str] = {
    # Python
    "open", "io.open", "os.path", "pathlib",
    "pathlib.path", "pathlib.read_text",
    # PHP
    "file_get_contents", "readfile", "fopen", "fread",
    "file", "include", "require", "include_once",
    "require_once", "file_put_contents", "fwrite",
    "fputs", "file_exists",
    # Java
    "filereader", "fileinputstream", "filechannel",
    "files.readallbytes", "files.readalllines",
    "paths.get", "new file",
    # .NET
    "file.readalltext", "file.readallbytes",
    "file.readalllines", "filestream",
    "streamreader", "file.openread",
    # Ruby
    "file.read", "file.open", "io.read",
    "pathname", "open-uri",
    # JavaScript / Node.js
    "fs.readfile", "fs.readfilesync",
    "fs.createreadstream", "fs.readdir",
    "fs.readdirsync", "fs.stat",
    # Go
    "os.readfile", "ioutil.readfile",
    "ioutil.readdir", "os.open",
    # Path traversal parameter names (recon signals)
    "page", "path", "dir", "directory",
    "document", "template", "load",
    "read", "show", "view", "display",
}
def _activate_path_traversal(rc) -> tuple[bool, str]:
    """Activate when file access functions are detected in tech_stack.

    Path traversal (directory traversal) allows attackers to access
    files and directories outside the web root by manipulating path
    references in user-controlled input. Common in file retrieval,
    template rendering, and document viewing functionality.

    Activates when:
      - ``has_path_traversal`` flag is set (forward-compatible)
      - ``path_traversal_endpoints`` list is populated (forward-compatible)
      - File access function keywords appear in tech_stack
      - Parameter-bearing URLs have path-traversal-like parameters
        (file, page, path, dir, document, template, include, etc.)
      - File upload is present (traversal via upload paths)
    """
    # Forward-compatible: check for dedicated path traversal attribute
    has_pt = _get_attr(rc, "has_path_traversal", False)
    if has_pt:
        return True, "path traversal signals detected in recon"

    pt_eps = _get_attr(rc, "path_traversal_endpoints", [])
    if pt_eps and len(pt_eps) > 0:
        return True, f"{len(pt_eps)} path traversal endpoint(s) found"

    # Check tech_stack for file access function keywords
    tech = _get_tech_stack(rc)
    if tech:
        tech_lower = " ".join(t.lower() for t in tech)
        matched = [kw for kw in _FILE_ACCESS_FUNCTIONS if kw in tech_lower]
        if matched:
            return True, f"file access function detected: {', '.join(matched[:3])}"

    # Parameter-bearing URLs with path traversal parameter names
    param_urls = _get_attr(rc, "parameter_bearing_urls", [])
    reasons = []
    if param_urls:
        traversal_params = {"file", "page", "path", "dir", "directory",
                           "document", "template", "include", "load",
                           "read", "show", "view", "display",
                           "folder", "root", "base", "href"}
        from urllib.parse import parse_qs, urlparse
        for url in param_urls:
            try:
                parsed = urlparse(url)
                params = parse_qs(parsed.query)
                param_names_lower = {p.lower() for p in params}
                if param_names_lower & traversal_params:
                    matched = param_names_lower & traversal_params
                    reasons.append(f"{len(param_urls)} URL(s) with traversal params")
                    break
            except Exception:
                continue

    # File upload can involve path traversal via upload paths
    has_upload = _get_attr(rc, "has_file_upload", False)
    if has_upload:
        reasons.append("file upload present")

    if reasons:
        return True, "possible path traversal context: " + "; ".join(reasons)

    return False, "no path traversal signals detected"


def _path_traversal_tools(recon_context) -> list[ToolTask]:
    """Build tool tasks for path traversal vulnerability testing.

    Tests for:
      - Directory traversal via ../ patterns (../etc/passwd, ..\\windows\\)
      - Path traversal via URL-encoded variants (%2e%2e/, ..\\;/, ....//)
      - Blind path traversal via file existence detection
      - Path traversal via file upload filenames
      - File disclosure via traversal (config files, source code)
      - Local File Inclusion (LFI) via path traversal
      - Remote File Inclusion (RFI) via traversal patterns
    """
    tools: list[ToolTask] = [
        ToolTask(
            tool_name="nuclei",
            description="Path traversal and LFI scanning (dot-dot-slash, encoded variants, config disclosure)",
            priority=10,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "lfi,path-traversal,traversal,disclosure"],
        ),
        ToolTask(
            tool_name="nuclei",
            description="Path traversal via file upload and RFI scanning",
            priority=20,
            timeout=300,
            args_template=["-u", "{target}", "-jsonl", "-silent",
                           "-severity", "medium,high,critical",
                           "-tags", "lfi,rfi,file-inclusion,upload,exposure"],
        ),
    ]
    return tools


# ── Phase: Command Injection Testing ─────────────────────────────────────

# Shell-execution functions and OS command interfaces by language
_CMD_EXECUTION_FUNCTIONS: set[str] = {
    # Python
    "os.system", "subprocess", "os.popen", "pty.spawn",
    "commands.getoutput", "subprocess.popen",
    # PHP
    "exec", "shell_exec", "system", "passthru", "popen",
    "proc_open", "pcntl_exec",
    # Java
    "runtime.exec", "runtime.getruntime.exec",
    "processbuilder", "processbuilder.start",
    # JavaScript / Node.js
    "child_process.exec", "child_process.execsync",
    "child_process.spawn", "child_process.execfile",
    "execSync", "execFileSync", "spawnSync",
    # Ruby
    "io.popen", "open3.popen3", "open3.capture3",
    "kernel.exec", "kernel.system",
    # .NET
    "process.start", "system.diagnostics.process",
    "cmd.exe", "powershell.exe",
    # Go
    "exec.command", "os/exec", "golang exec",
    # Perl
    "perl system", "perl exec", "perl backtick",
    # Shared concepts
    "cmd", "command", "shell", "sh",
    "bash", "powershell", "pwsh",
}
