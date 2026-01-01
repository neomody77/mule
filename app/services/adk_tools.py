"""
Google ADK 工具定义

为 coding agent 定义文件操作、命令执行等工具
"""
import os
import glob as glob_module
import subprocess
import re
from pathlib import Path
from typing import Optional


def read_file(file_path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> dict:
    """
    Read content from a file.

    Args:
        file_path: Absolute path to the file to read
        offset: Line number to start reading from (1-based)
        limit: Maximum number of lines to read

    Returns:
        dict with status and content or error message
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "error": f"File not found: {file_path}"}

        if not path.is_file():
            return {"status": "error", "error": f"Not a file: {file_path}"}

        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()

        # Apply offset and limit
        start = (offset - 1) if offset and offset > 0 else 0
        end = (start + limit) if limit else len(lines)
        selected_lines = lines[start:end]

        # Format with line numbers
        result_lines = []
        for i, line in enumerate(selected_lines, start=start + 1):
            result_lines.append(f"{i:6d}→{line.rstrip()}")

        return {
            "status": "success",
            "content": "\n".join(result_lines),
            "total_lines": len(lines)
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def write_file(file_path: str, content: str) -> dict:
    """
    Write content to a file, creating it if necessary.

    Args:
        file_path: Absolute path to the file to write
        content: Content to write to the file

    Returns:
        dict with status and message
    """
    try:
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

        return {
            "status": "success",
            "message": f"Successfully wrote {len(content)} bytes to {file_path}"
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def edit_file(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> dict:
    """
    Edit a file by replacing text.

    Args:
        file_path: Absolute path to the file to edit
        old_string: Text to find and replace
        new_string: Text to replace with
        replace_all: If True, replace all occurrences; if False, replace only first

    Returns:
        dict with status and message
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {"status": "error", "error": f"File not found: {file_path}"}

        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()

        if old_string not in content:
            return {"status": "error", "error": "old_string not found in file"}

        if not replace_all:
            # Check uniqueness
            count = content.count(old_string)
            if count > 1:
                return {
                    "status": "error",
                    "error": f"old_string found {count} times. Use replace_all=True or provide more context."
                }

        if replace_all:
            new_content = content.replace(old_string, new_string)
            count = content.count(old_string)
        else:
            new_content = content.replace(old_string, new_string, 1)
            count = 1

        with open(path, 'w', encoding='utf-8') as f:
            f.write(new_content)

        return {
            "status": "success",
            "message": f"Replaced {count} occurrence(s) in {file_path}"
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_bash(command: str, timeout: int = 120, workdir: Optional[str] = None) -> dict:
    """
    Execute a bash command.

    Args:
        command: The bash command to execute
        timeout: Timeout in seconds (default 120)
        workdir: Working directory for the command

    Returns:
        dict with exit_code, stdout, and stderr
    """
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=workdir or os.getcwd()
        )

        return {
            "status": "success",
            "exit_code": result.returncode,
            "stdout": result.stdout[:30000] if result.stdout else "",
            "stderr": result.stderr[:10000] if result.stderr else ""
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": f"Command timed out after {timeout} seconds"
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def glob_search(pattern: str, path: Optional[str] = None) -> dict:
    """
    Search for files matching a glob pattern.

    Args:
        pattern: Glob pattern to match (e.g., "**/*.py")
        path: Directory to search in (default: current directory)

    Returns:
        dict with list of matching files
    """
    try:
        search_path = Path(path) if path else Path.cwd()

        if not search_path.exists():
            return {"status": "error", "error": f"Path not found: {path}"}

        full_pattern = str(search_path / pattern)
        matches = glob_module.glob(full_pattern, recursive=True)

        # Sort by modification time (newest first)
        matches.sort(key=lambda x: os.path.getmtime(x), reverse=True)

        # Limit results
        matches = matches[:100]

        return {
            "status": "success",
            "files": matches,
            "count": len(matches)
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def grep_search(
    pattern: str,
    path: Optional[str] = None,
    file_glob: Optional[str] = None,
    case_insensitive: bool = False,
    context_lines: int = 0
) -> dict:
    """
    Search for a regex pattern in files.

    Args:
        pattern: Regex pattern to search for
        path: Directory or file to search in
        file_glob: Glob pattern to filter files (e.g., "*.py")
        case_insensitive: If True, ignore case
        context_lines: Number of context lines to show

    Returns:
        dict with matching lines and files
    """
    try:
        search_path = Path(path) if path else Path.cwd()

        if not search_path.exists():
            return {"status": "error", "error": f"Path not found: {path}"}

        flags = re.IGNORECASE if case_insensitive else 0
        regex = re.compile(pattern, flags)

        results = []
        files_with_matches = set()

        # Get files to search
        if search_path.is_file():
            files = [search_path]
        else:
            glob_pattern = file_glob or "**/*"
            files = list(search_path.glob(glob_pattern))

        for file_path in files[:1000]:  # Limit files
            if not file_path.is_file():
                continue

            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()

                for i, line in enumerate(lines):
                    if regex.search(line):
                        files_with_matches.add(str(file_path))

                        # Get context
                        start = max(0, i - context_lines)
                        end = min(len(lines), i + context_lines + 1)

                        context = []
                        for j in range(start, end):
                            prefix = ">" if j == i else " "
                            context.append(f"{j+1:6d}{prefix}{lines[j].rstrip()}")

                        results.append({
                            "file": str(file_path),
                            "line": i + 1,
                            "content": line.rstrip(),
                            "context": "\n".join(context) if context_lines > 0 else None
                        })

                        if len(results) >= 100:  # Limit results
                            break
            except Exception:
                continue

            if len(results) >= 100:
                break

        return {
            "status": "success",
            "matches": results,
            "files_with_matches": list(files_with_matches),
            "match_count": len(results)
        }
    except re.error as e:
        return {"status": "error", "error": f"Invalid regex: {e}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_directory(path: str) -> dict:
    """
    List contents of a directory.

    Args:
        path: Directory path to list

    Returns:
        dict with list of files and directories
    """
    try:
        dir_path = Path(path)

        if not dir_path.exists():
            return {"status": "error", "error": f"Path not found: {path}"}

        if not dir_path.is_dir():
            return {"status": "error", "error": f"Not a directory: {path}"}

        items = []
        for item in sorted(dir_path.iterdir()):
            stat = item.stat()
            items.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": stat.st_size if item.is_file() else None,
            })

        return {
            "status": "success",
            "items": items,
            "count": len(items)
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# Export all tools
ALL_TOOLS = [
    read_file,
    write_file,
    edit_file,
    run_bash,
    glob_search,
    grep_search,
    list_directory,
]
