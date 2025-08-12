from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable
import json
import os
import shlex
import subprocess
import sys
import tempfile

import yaml
from mcp.server.fastmcp import FastMCP


mcp = FastMCP("ansible-mcp")


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _run_command(command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    process = subprocess.Popen(
        command,
        cwd=str(cwd) if cwd else None,
        env={**os.environ.copy(), **(env or {})},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    stdout, stderr = process.communicate()
    return process.returncode, stdout, stderr


def _serialize_playbook(playbook: Any) -> str:
    if isinstance(playbook, str):
        return playbook
    return yaml.safe_dump(playbook, sort_keys=False)


def _dict_to_module_args(module_args: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in module_args.items():
        if isinstance(value, (dict, list)):
            parts.append(f"{key}={shlex.quote(json.dumps(value))}")
        elif isinstance(value, bool):
            parts.append(f"{key}={'yes' if value else 'no'}")
        elif value is None:
            parts.append(f"{key}=")
        else:
            parts.append(f"{key}={shlex.quote(str(value))}")
    return " ".join(parts)


# -------------------------
# Project integration layer
# -------------------------

CONFIG_ENV_VAR = "MCP_ANSIBLE_CONFIG"
DEFAULT_CONFIG_FILE = Path.home() / ".config" / "mcp-ansible" / "config.json"
LOCAL_CONFIG_FILE = Path.cwd() / "mcp_ansible.config.json"


@dataclass
class ProjectDefinition:
    name: str
    root: str
    inventory: str | None = None
    roles_paths: list[str] | None = None
    collections_paths: list[str] | None = None
    env: dict[str, str] | None = None


@dataclass
class ServerConfiguration:
    projects: dict[str, ProjectDefinition]
    defaults: dict[str, Any]


def _config_path() -> Path:
    path = os.environ.get(CONFIG_ENV_VAR)
    if path:
        return Path(path).expanduser().resolve()
    # prefer local config if present, otherwise default user config
    return LOCAL_CONFIG_FILE if LOCAL_CONFIG_FILE.exists() else DEFAULT_CONFIG_FILE


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _ensure_directory(path.parent)
    path.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")


def _load_config() -> ServerConfiguration:
    path = _config_path()
    raw = _read_json(path)
    projects_raw = raw.get("projects") or {}
    projects: dict[str, ProjectDefinition] = {}
    for name, cfg in projects_raw.items():
        projects[name] = ProjectDefinition(
            name=name,
            root=cfg.get("root", ""),
            inventory=cfg.get("inventory"),
            roles_paths=list(cfg.get("roles_paths") or []) or None,
            collections_paths=list(cfg.get("collections_paths") or []) or None,
            env=dict(cfg.get("env") or {}) or None,
        )
    defaults = dict(raw.get("defaults") or {})
    return ServerConfiguration(projects=projects, defaults=defaults)


def _save_config(config: ServerConfiguration) -> dict[str, Any]:
    path = _config_path()
    payload = {
        "projects": {name: asdict(defn) for name, defn in config.projects.items()},
        "defaults": config.defaults,
    }
    _write_json(path, payload)
    return {"path": str(path), "projects": list(config.projects.keys())}


def _project_env(defn: ProjectDefinition) -> dict[str, str]:
    env: dict[str, str] = {}
    if defn.roles_paths:
        env["ANSIBLE_ROLES_PATH"] = os.pathsep.join(defn.roles_paths)
    if defn.collections_paths:
        env["ANSIBLE_COLLECTIONS_PATHS"] = os.pathsep.join(defn.collections_paths)
    if defn.env:
        env.update(defn.env)
    return env


def _resolve_project(config: ServerConfiguration, name: str | None) -> ProjectDefinition | None:
    # Explicit project name wins
    if name:
        return config.projects.get(str(name))
    # Environment override takes precedence over saved default
    env_root = os.environ.get("MCP_ANSIBLE_PROJECT_ROOT")
    if env_root:
        return _project_from_env()
    # Fall back to saved default
    project_name = config.defaults.get("project")
    if not project_name:
        return None
    return config.projects.get(str(project_name))


def _discover_playbooks(root: Path) -> list[str]:
    excluded_dirs = {".git", ".venv", "venv", "__pycache__", "collections", "inventory", "roles", "node_modules"}
    results: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune excluded directories
        dirnames[:] = [d for d in dirnames if d not in excluded_dirs]
        for filename in filenames:
            if not (filename.endswith(".yml") or filename.endswith(".yaml")):
                continue
            path = Path(dirpath) / filename
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    results.append(str(path))
            except Exception:
                # skip invalid YAML
                continue
    return sorted(results)


def _split_paths(value: str | None) -> list[str] | None:
    if not value:
        return None
    parts = [p for p in value.split(os.pathsep) if p]
    return [str(Path(p).expanduser().resolve()) for p in parts] or None


def _project_from_env() -> ProjectDefinition | None:
    root = os.environ.get("MCP_ANSIBLE_PROJECT_ROOT")
    if not root:
        return None
    name = os.environ.get("MCP_ANSIBLE_PROJECT_NAME", "env")
    inventory = os.environ.get("MCP_ANSIBLE_INVENTORY")
    roles_paths = _split_paths(os.environ.get("MCP_ANSIBLE_ROLES_PATH"))
    collections_paths = _split_paths(os.environ.get("MCP_ANSIBLE_COLLECTIONS_PATHS"))
    # Capture any extra env with MCP_ANSIBLE_ENV_* prefix
    extra_env: dict[str, str] = {}
    for key, value in os.environ.items():
        if key.startswith("MCP_ANSIBLE_ENV_"):
            extra_env[key.replace("MCP_ANSIBLE_ENV_", "")] = value
    return ProjectDefinition(
        name=name,
        root=str(Path(root).expanduser().resolve()),
        inventory=str(Path(inventory).expanduser().resolve()) if inventory else None,
        roles_paths=roles_paths,
        collections_paths=collections_paths,
        env=extra_env or None,
    )


def _extract_hosts_from_inventory_json(data: dict[str, Any]) -> tuple[set[str], dict[str, list[str]]]:
    hosts: set[str] = set()
    groups: dict[str, list[str]] = {}
    # Hostvars may include all hosts
    meta = data.get("_meta") or {}
    hostvars = meta.get("hostvars") or {}
    hosts.update(hostvars.keys())
    # Each top-level group may have 'hosts'
    for group_name, group_def in data.items():
        if group_name == "_meta":
            continue
        if isinstance(group_def, dict):
            group_hosts = group_def.get("hosts") or []
            if isinstance(group_hosts, list):
                for h in group_hosts:
                    if isinstance(h, str):
                        hosts.add(h)
                if group_hosts:
                    groups[group_name] = [str(h) for h in group_hosts]
    return hosts, groups


@mcp.tool(name="ansible-inventory")
def ansible_inventory(inventory: str | None = None, include_hostvars: bool | None = None, cwd: str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """List Ansible inventory hosts and groups using the ansible-inventory CLI.

    Args:
        inventory: Optional inventory path or host list (e.g., 'hosts.ini' or 'localhost,').
        include_hostvars: If true, include hostvars keys in the response (not the full values).
        cwd: Optional working directory to run the command in.
    Returns:
        Dict with keys: ok, rc, hosts, groups, hostvars_keys (optional), command, stderr
    """
    cmd: list[str] = ["ansible-inventory", "--list"]
    if inventory:
        cmd.extend(["-i", inventory])
    rc, out, err = _run_command(cmd, cwd=Path(cwd) if cwd else None, env=env)
    result: dict[str, Any] = {"ok": rc == 0, "rc": rc, "command": shlex.join(cmd), "stderr": err}
    if rc != 0:
        result["stdout"] = out
        return result
    try:
        data = json.loads(out)
    except Exception:
        result["stdout"] = out
        return result
    hosts, groups = _extract_hosts_from_inventory_json(data)
    result["hosts"] = sorted(hosts)
    result["groups"] = {k: sorted(v) for k, v in groups.items()}
    if include_hostvars:
        meta = data.get("_meta") or {}
        hostvars = meta.get("hostvars") or {}
        result["hostvars_keys"] = sorted([str(k) for k in hostvars.keys()])
    return result


@mcp.tool(name="register-project")
def register_project(name: str, root: str, inventory: str | None = None, roles_paths: list[str] | None = None, collections_paths: list[str] | None = None, env: dict[str, str] | None = None, make_default: bool | None = None) -> dict[str, Any]:
    """Register an existing Ansible project with this MCP server.

    Args:
        name: Unique project name.
        root: Project root directory.
        inventory: Optional default inventory file or directory path.
        roles_paths: Optional list to export via ANSIBLE_ROLES_PATH.
        collections_paths: Optional list to export via ANSIBLE_COLLECTIONS_PATHS.
        env: Optional extra environment variables to export for this project.
        make_default: If true, set this project as the default.
    Returns:
        Dict: saved config path and project list
    """
    cfg = _load_config()
    cfg.projects[name] = ProjectDefinition(
        name=name,
        root=str(Path(root).resolve()),
        inventory=str(Path(inventory).resolve()) if inventory else None,
        roles_paths=[str(Path(p).resolve()) for p in (roles_paths or [])] or None,
        collections_paths=[str(Path(p).resolve()) for p in (collections_paths or [])] or None,
        env=env or None,
    )
    if make_default:
        cfg.defaults["project"] = name
    return _save_config(cfg)


@mcp.tool(name="list-projects")
def list_projects() -> dict[str, Any]:
    """List all registered Ansible projects and the default selection."""
    cfg = _load_config()
    return {
        "default": cfg.defaults.get("project"),
        "projects": {k: asdict(v) for k, v in cfg.projects.items()},
        "config_path": str(_config_path()),
    }


@mcp.tool(name="project-playbooks")
def project_playbooks(project: str | None = None) -> dict[str, Any]:
    """Discover playbooks (YAML lists) under the project root."""
    cfg = _load_config()
    defn = _resolve_project(cfg, project)
    if not defn:
        return {"ok": False, "error": "No project specified and no default set"}
    root = Path(defn.root)
    if not root.exists():
        return {"ok": False, "error": f"Project root not found: {root}"}
    return {"ok": True, "root": str(root), "playbooks": _discover_playbooks(root)}


@mcp.tool(name="project-run-playbook")
def project_run_playbook(playbook_path: str, project: str | None = None, extra_vars: dict[str, Any] | None = None, tags: list[str] | None = None, skip_tags: list[str] | None = None, limit: str | None = None, check: bool | None = None, diff: bool | None = None, verbose: int | None = None) -> dict[str, Any]:
    """Run a playbook within a registered project, applying its inventory and environment."""
    cfg = _load_config()
    defn = _resolve_project(cfg, project)
    if not defn:
        return {"ok": False, "error": "No project specified and no default set"}
    env = _project_env(defn)
    cwd = defn.root
    return ansible_playbook(
        playbook_path=str(Path(playbook_path).resolve()),
        inventory=defn.inventory,
        extra_vars=extra_vars,
        tags=tags,
        skip_tags=skip_tags,
        limit=limit,
        cwd=cwd,
        check=check,
        diff=diff,
        verbose=verbose,
        env=env,
    )


@mcp.tool(name="create-playbook")
def create_playbook(playbook: Any, output_path: str | None = None) -> dict[str, Any]:
    """Create an Ansible playbook from YAML string or object.

    Args:
        playbook: YAML string or Python object representing the playbook.
        output_path: Optional path to write the playbook file. If not provided, a temp file is created.
    Returns:
        A dict with keys: path, bytes_written, preview
    """
    yaml_text = _serialize_playbook(playbook)
    if output_path:
        path = Path(output_path).resolve()
        _ensure_directory(path.parent)
    else:
        tmp = tempfile.NamedTemporaryFile(prefix="playbook_", suffix=".yml", delete=False)
        path = Path(tmp.name)
        tmp.close()
    data = yaml_text.encode("utf-8")
    path.write_bytes(data)
    preview = "\n".join(yaml_text.splitlines()[:50])
    return {"path": str(path), "bytes_written": len(data), "preview": preview}


@mcp.tool(name="validate-playbook")
def validate_playbook(playbook_path: str, inventory: str | None = None, cwd: str | None = None) -> dict[str, Any]:
    """Validate playbook syntax using ansible-playbook --syntax-check.

    Args:
        playbook_path: Path to the playbook file.
        inventory: Optional inventory path or host list.
        cwd: Optional working directory to run the command in.
    Returns:
        A dict with keys: ok (bool), rc, stdout, stderr
    """
    cmd: list[str] = ["ansible-playbook", "--syntax-check", playbook_path]
    if inventory:
        cmd.extend(["-i", inventory])
    rc, out, err = _run_command(cmd, cwd=Path(cwd) if cwd else None)
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err}


@mcp.tool(name="ansible-playbook")
def ansible_playbook(playbook_path: str, inventory: str | None = None, extra_vars: dict[str, Any] | None = None, tags: list[str] | None = None, skip_tags: list[str] | None = None, limit: str | None = None, cwd: str | None = None, check: bool | None = None, diff: bool | None = None, verbose: int | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run an Ansible playbook.

    Args:
        playbook_path: Path to the playbook file.
        inventory: Optional inventory path or host list.
        extra_vars: Dict of variables passed via --extra-vars.
        tags: List of tags to include.
        skip_tags: List of tags to skip.
        limit: Host limit pattern.
        cwd: Working directory for the command.
        check: If true, run in check mode.
        diff: If true, show diffs.
        verbose: Verbosity level (1-4) corresponding to -v, -vv, -vvv, -vvvv.
    Returns:
        A dict with keys: ok (bool), rc, stdout, stderr, command
    """
    cmd: list[str] = ["ansible-playbook", playbook_path]
    if inventory:
        cmd.extend(["-i", inventory])
    if extra_vars:
        cmd.extend(["--extra-vars", json.dumps(extra_vars)])
    if tags:
        cmd.extend(["--tags", ",".join(tags)])
    if skip_tags:
        cmd.extend(["--skip-tags", ",".join(skip_tags)])
    if limit:
        cmd.extend(["--limit", limit])
    if check:
        cmd.append("--check")
    if diff:
        cmd.append("--diff")
    if verbose:
        cmd.append("-" + ("v" * max(1, min(verbose, 4))))
    rc, out, err = _run_command(cmd, cwd=Path(cwd) if cwd else None, env=env)
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err, "command": shlex.join(cmd)}


@mcp.tool(name="ansible-task")
def ansible_task(host_pattern: str, module: str, args: dict[str, Any] | str | None = None, inventory: str | None = None, become: bool | None = None, become_user: str | None = None, check: bool | None = None, diff: bool | None = None, cwd: str | None = None, verbose: int | None = None, connection: str | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run an ad-hoc Ansible task using the ansible CLI.

    Args:
        host_pattern: Inventory host pattern to target (e.g., 'all' or 'web')
        module: Module name (e.g., 'ping', 'shell')
        args: Module arguments, either dict or string
        inventory: Inventory path or host list
        become: Use privilege escalation
        become_user: Target user when using become
        check: Check mode
        diff: Show diffs
        cwd: Working directory
        verbose: Verbosity level 1-4
        connection: Connection type (e.g., 'local', 'ssh'). Defaults to 'local' when targeting localhost.
    Returns:
        A dict with keys: ok (bool), rc, stdout, stderr, command
    """
    cmd: list[str] = ["ansible", host_pattern, "-m", module]
    if args is not None:
        if isinstance(args, dict):
            cmd.extend(["-a", _dict_to_module_args(args)])
        else:
            cmd.extend(["-a", str(args)])
    if inventory:
        cmd.extend(["-i", inventory])
    # Default to local connection when targeting localhost, unless explicitly overridden
    use_conn = connection
    if use_conn is None and host_pattern in {"localhost", "127.0.0.1"}:
        use_conn = "local"
    if use_conn:
        cmd.extend(["-c", use_conn])
    if become:
        cmd.append("--become")
    if become_user:
        cmd.extend(["--become-user", become_user])
    if check:
        cmd.append("--check")
    if diff:
        cmd.append("--diff")
    if verbose:
        cmd.append("-" + ("v" * max(1, min(verbose, 4))))
    rc, out, err = _run_command(cmd, cwd=Path(cwd) if cwd else None, env=env)
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err, "command": shlex.join(cmd)}


@mcp.tool(name="ansible-role")
def ansible_role(role_name: str, hosts: str = "all", inventory: str | None = None, vars: dict[str, Any] | None = None, cwd: str | None = None, check: bool | None = None, diff: bool | None = None, verbose: int | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Execute an Ansible role by generating a temporary playbook.

    Args:
        role_name: Name of the role to execute.
        hosts: Target hosts pattern.
        inventory: Inventory path or host list.
        vars: Extra vars for the role.
        cwd: Working directory.
        check: Check mode.
        diff: Show diffs.
        verbose: Verbosity level 1-4.
    Returns:
        ansible_playbook() result dict
    """
    playbook_obj = [
        {
            "hosts": hosts,
            "gather_facts": False,
            "roles": [
                {"role": role_name, **({"vars": vars} if vars else {})}
            ],
        }
    ]
    tmp = create_playbook(playbook_obj)
    return ansible_playbook(
        playbook_path=tmp["path"],
        inventory=inventory,
        cwd=cwd,
        check=check,
        diff=diff,
        verbose=verbose,
        env=env,
    )


@mcp.tool(name="create-role-structure")
def create_role_structure(base_path: str, role_name: str) -> dict[str, Any]:
    """Generate the standard Ansible role directory structure.

    Args:
        base_path: Directory where the role directory will be created.
        role_name: Name of the role directory.
    Returns:
        Dict with keys: created (list[str]), role_path
    """
    base = Path(base_path).resolve()
    role_dir = base / role_name
    subdirs = [
        "defaults",
        "files",
        "handlers",
        "meta",
        "tasks",
        "templates",
        "tests",
        "vars",
    ]
    created: list[str] = []
    for sub in subdirs:
        target = role_dir / sub
        _ensure_directory(target)
        created.append(str(target))
    # create main.yml for common directories
    for sub in ("defaults", "handlers", "meta", "tasks", "vars"):
        main_file = role_dir / sub / "main.yml"
        if not main_file.exists():
            main_file.write_text("---\n", encoding="utf-8")
            created.append(str(main_file))
    return {"created": created, "role_path": str(role_dir)}


if __name__ == "__main__":
    mcp.run(transport="stdio")


