"""Tool schemas for the coding assistant: file ops plus shell."""

from __future__ import annotations

# Read-only tools allowed while planning.
PLAN_TOOL_NAMES = ("read_file", "list_files", "search_files", "run_command")

CODING_TOOLS: list[dict] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file. Returns the file content with line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (relative to working directory)."},
                "start_line": {"type": "integer", "description": "Optional: start reading from this line number (1-based)."},
                "end_line": {"type": "integer", "description": "Optional: stop reading at this line number (inclusive)."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Create a new file or completely overwrite an existing file with new content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file (relative to working directory)."},
                "content": {"type": "string", "description": "The full content to write to the file."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Edit a file by replacing old_string with new_string. Copy old_string "
            "verbatim from a recent read_file (including indentation). It must be "
            "unique unless replace_all is true. Minor trailing-whitespace/CRLF "
            "differences are tolerated; if no match is found the error includes the "
            "closest region so you can correct it. Use write_file for new files."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file."},
                "old_string": {"type": "string", "description": "The exact text to find and replace. Must be unique unless replace_all is true."},
                "new_string": {"type": "string", "description": "The replacement text."},
                "replace_all": {"type": "boolean", "description": "Replace every occurrence instead of requiring a unique match. Default false.", "default": False},
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "list_files",
        "description": "List files and directories in a path. Returns a tree-like listing.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list (relative to working directory). Defaults to '.'.",
                    "default": ".",
                },
                "pattern": {
                    "type": "string",
                    "description": "Optional glob pattern to filter files (e.g. '*.py', '**/*.ts').",
                },
            },
            "required": [],
        },
    },
    {
        "name": "search_files",
        "description": "Search for a text pattern (regex) across files in the working directory. Returns matching lines with file paths and line numbers.",
        "parameters": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
                "path": {
                    "type": "string",
                    "description": "Directory or file to search in. Defaults to '.'.",
                    "default": ".",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Optional glob to filter which files to search (e.g. '*.py').",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "run_command",
        "description": (
            "Run a shell command in the working directory. Use for: running tests, "
            "installing packages, git operations, building, linting, etc. "
            "Returns stdout, stderr, and exit code."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to execute."},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds. Defaults to 120.",
                    "default": 120,
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "install_package",
        "description": (
            "Install a Python package using pip. Use this when a command fails because a "
            "package is missing (e.g. pytest, flask, requests). Also use this to install "
            "project dependencies from requirements.txt or pyproject.toml."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package name(s) to install (e.g. 'pytest', 'flask requests', '-r requirements.txt', '-e .').",
                },
            },
            "required": ["package"],
        },
    },
    {
        "name": "update_memory",
        "description": (
            "Update the session memory with your current progress. Call this periodically "
            "(every 3-5 tool calls) to checkpoint your work. This memory persists even when "
            "older messages are trimmed from context. IMPORTANT: Call this after completing "
            "each major step of your plan."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "current_step": {
                    "type": "string",
                    "description": "What you are currently working on.",
                },
                "completed_step": {
                    "type": "string",
                    "description": "A step you just finished (will be added to the completed list).",
                },
                "decision": {
                    "type": "string",
                    "description": "A key decision you made (e.g. 'Using SQLite instead of PostgreSQL for simplicity').",
                },
                "error": {
                    "type": "string",
                    "description": "An error you encountered and how you resolved it.",
                },
            },
            "required": [],
        },
    },
]


# Handled by the session, not the executor: it asks for authorization, then
# fans out read-only sub-agents.
DISPATCH_AGENTS_TOOL: dict = {
    "name": "dispatch_agents",
    "description": (
        "Delegate independent, READ-ONLY investigation subtasks to parallel sub-agents "
        "and get their findings back. Use when a task needs exploring several distinct "
        "areas at once (e.g. 'how does auth work', 'where are DB models', 'find the API routes'). "
        "Sub-agents cannot modify files. Requires user authorization before running."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "2-5 independent investigation questions, each self-contained.",
            },
        },
        "required": ["tasks"],
    },
}


def to_openai_format(tools: list[dict] | None = None) -> list[dict]:
    tools = tools or CODING_TOOLS
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in tools
    ]
