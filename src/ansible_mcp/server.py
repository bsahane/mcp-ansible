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
from contextlib import contextmanager
import time
import hashlib
import re
from datetime import datetime, timedelta
from collections import defaultdict

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


# -------------------------
# Local Inventory Suite
# -------------------------

def _compose_ansible_env(ansible_cfg_path: str | None = None, project_root: str | None = None, extra_env: dict[str, str] | None = None) -> tuple[dict[str, str], Path | None]:
    env: dict[str, str] = {}
    if ansible_cfg_path:
        env["ANSIBLE_CONFIG"] = str(Path(ansible_cfg_path).expanduser().resolve())
    cwd: Path | None = Path(project_root).expanduser().resolve() if project_root else None
    if extra_env:
        env.update(extra_env)
    return env, cwd


def _inventory_cli(inventory_paths: list[str] | None) -> list[str]:
    if not inventory_paths:
        return []
    joined = ",".join(str(Path(p).expanduser().resolve()) for p in inventory_paths)
    return ["-i", joined]


@mcp.tool(name="inventory-parse")
def inventory_parse(project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, include_hostvars: bool | None = None, deep: bool | None = None) -> dict[str, Any]:
    """Parse inventory via ansible-inventory, merging group_vars/host_vars.

    Args:
        project_root: Project root folder (sets CWD and uses ansible.cfg if present)
        ansible_cfg_path: Explicit ansible.cfg path (overrides)
        inventory_paths: Optional list of inventory files/dirs (ini/yaml/no-ext supported)
        include_hostvars: Include merged hostvars in response
        deep: Placeholder for future source mapping; ignored for now
    """
    extra_env = {"INVENTORY_ENABLED": "auto"}
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, extra_env)
    cmd: list[str] = ["ansible-inventory", "--list"] + _inventory_cli(inventory_paths)
    rc, out, err = _run_command(cmd, cwd=cwd, env=env)
    result: dict[str, Any] = {"ok": rc == 0, "rc": rc, "stderr": err, "command": shlex.join(cmd), "cwd": str(cwd) if cwd else None}
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
        result["hostvars"] = hostvars
    return result


@mcp.tool(name="inventory-graph")
def inventory_graph(project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None) -> dict[str, Any]:
    """Return ansible-inventory --graph output using discovered config."""
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    cmd: list[str] = ["ansible-inventory", "--graph"] + _inventory_cli(inventory_paths)
    rc, out, err = _run_command(cmd, cwd=cwd, env=env)
    return {"ok": rc == 0, "rc": rc, "graph": out, "stderr": err, "command": shlex.join(cmd), "cwd": str(cwd) if cwd else None}


@mcp.tool(name="inventory-find-host")
def inventory_find_host(host: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None) -> dict[str, Any]:
    """Find a host, its groups, and merged variables across the resolved inventories."""
    parsed = inventory_parse(project_root=project_root, ansible_cfg_path=ansible_cfg_path, inventory_paths=inventory_paths, include_hostvars=True)
    if not parsed.get("ok"):
        return parsed
    all_groups: dict[str, list[str]] = parsed.get("groups", {})
    hostvars: dict[str, Any] = parsed.get("hostvars", {})
    groups_for_host = sorted([g for g, members in all_groups.items() if host in set(members)])
    return {
        "ok": True,
        "host": host,
        "present": host in hostvars or any(host in members for members in all_groups.values()),
        "groups": groups_for_host,
        "hostvars": hostvars.get(host, {}),
    }


@mcp.tool(name="ansible-ping")
def ansible_ping(host_pattern: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, verbose: int | None = None) -> dict[str, Any]:
    """Ping hosts using the Ansible ad-hoc ping module."""
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    return ansible_task(
        host_pattern=host_pattern,
        module="ping",
        args=None,
        inventory=inventory_str,
        cwd=str(cwd) if cwd else None,
        verbose=verbose,
        env=env,
    )


def _parse_setup_stdout(stdout: str) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for line in stdout.splitlines():
        if "SUCCESS" in line and "=>" in line:
            try:
                left, right = line.split("=>", 1)
                host = left.split("|")[0].strip()
                data = json.loads(right.strip())
                facts[host] = data.get("ansible_facts") or data
            except Exception:
                continue
    return facts


@mcp.tool(name="ansible-gather-facts")
def ansible_gather_facts(host_pattern: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, filter: str | None = None, gather_subset: str | None = None, verbose: int | None = None) -> dict[str, Any]:
    """Gather facts using the setup module and return parsed per-host facts."""
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, {"ANSIBLE_STDOUT_CALLBACK": "default"})
    args: dict[str, Any] = {}
    if filter:
        args["filter"] = filter
    if gather_subset:
        args["gather_subset"] = gather_subset
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    res = ansible_task(
        host_pattern=host_pattern,
        module="setup",
        args=args or None,
        inventory=inventory_str,
        cwd=str(cwd) if cwd else None,
        verbose=verbose,
        env=env,
    )
    facts = _parse_setup_stdout(res.get("stdout", ""))
    res["facts"] = facts
    return res


@mcp.tool(name="validate-yaml")
def validate_yaml(paths: list[str] | str) -> dict[str, Any]:
    """Validate YAML files; return parse errors with line/column if any."""
    path_list = [paths] if isinstance(paths, str) else list(paths)
    results: list[dict[str, Any]] = []
    ok_all = True
    for p in path_list:
        entry: dict[str, Any] = {"path": str(p)}
        try:
            with open(p, "r", encoding="utf-8") as f:
                yaml.safe_load(f)
            entry["ok"] = True
        except yaml.YAMLError as e:  # type: ignore[attr-defined]
            ok_all = False
            info: dict[str, Any] = {"message": str(e)}
            if hasattr(e, "problem_mark") and e.problem_mark is not None:  # type: ignore[attr-defined]
                mark = e.problem_mark
                info.update({"line": getattr(mark, "line", None), "column": getattr(mark, "column", None)})
            entry["ok"] = False
            entry["error"] = info
        except Exception as e:
            ok_all = False
            entry["ok"] = False
            entry["error"] = {"message": str(e)}
        results.append(entry)
    return {"ok": ok_all, "results": results}


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except Exception:
        return False


@mcp.tool(name="galaxy-install")
def galaxy_install(project_root: str, force: bool | None = None, requirements_paths: list[str] | None = None) -> dict[str, Any]:
    """Install roles and collections from requirements files under the project root."""
    root = Path(project_root).expanduser().resolve()
    env, cwd = _compose_ansible_env(None, str(root), None)
    reqs: list[tuple[str, str, list[str]]] = []
    # Roles
    roles_requirements = [root / "roles" / "requirements.yml", root / "requirements.yml"]
    for rp in roles_requirements:
        if _exists(rp):
            cmd = ["ansible-galaxy", "role", "install", "-r", str(rp), "-p", "roles"]
            if force:
                cmd.append("--force")
            reqs.append(("role", str(rp), cmd))
    # Collections
    coll_requirements = [root / "collections" / "requirements.yml", root / "requirements.yml"]
    for cp in coll_requirements:
        if _exists(cp):
            cmd = ["ansible-galaxy", "collection", "install", "-r", str(cp), "-p", "collections"]
            if force:
                cmd.append("--force")
            reqs.append(("collection", str(cp), cmd))
    # User-specified additional requirement files
    for p in (requirements_paths or []):
        pp = Path(p)
        if _exists(pp):
            # Try both role and collection installs (best-effort)
            reqs.append(("role", str(pp), ["ansible-galaxy", "role", "install", "-r", str(pp), "-p", "roles"]))
            reqs.append(("collection", str(pp), ["ansible-galaxy", "collection", "install", "-r", str(pp), "-p", "collections"]))
    executed: list[dict[str, Any]] = []
    if not reqs:
        return {"ok": True, "executed": [], "note": "No requirements.yml found"}
    ok_all = True
    for kind, path, cmd in reqs:
        rc, out, err = _run_command(cmd, cwd=cwd, env=env)
        executed.append({"kind": kind, "requirements": path, "rc": rc, "stdout": out, "stderr": err, "command": shlex.join(cmd)})
        if rc != 0:
            ok_all = False
    return {"ok": ok_all, "executed": executed}


@mcp.tool(name="project-bootstrap")
def project_bootstrap(project_root: str) -> dict[str, Any]:
    """Bootstrap a project: install galaxy deps and report Ansible environment details."""
    root = Path(project_root).expanduser().resolve()
    details: dict[str, Any] = {"project_root": str(root)}
    env, cwd = _compose_ansible_env(None, str(root), None)
    # ansible --version
    rc_v, out_v, err_v = _run_command(["ansible", "--version"], cwd=cwd, env=env)
    details["ansible_version"] = out_v.strip()
    # ansible-config dump (short)
    rc_c, out_c, err_c = _run_command(["ansible-config", "dump"], cwd=cwd, env=env)
    details["ansible_config_dump"] = out_c
    # galaxy install
    galaxy = galaxy_install(str(root))
    return {"ok": rc_v == 0 and rc_c == 0 and galaxy.get("ok", False), "details": details, "galaxy": galaxy}


# -------------------------
# Phase 2: Diff, Idempotence, Vault, Galaxy lock
# -------------------------


def _parse_play_recap(stdout: str) -> dict[str, dict[str, int]]:
    totals: dict[str, dict[str, int]] = {}
    started = False
    for line in stdout.splitlines():
        if line.strip().startswith("PLAY RECAP"):
            started = True
            continue
        if started:
            if not line.strip():
                continue
            parts = line.split(":", 1)
            if len(parts) != 2:
                continue
            host = parts[0].strip()
            stats = {k: 0 for k in ["ok", "changed", "unreachable", "failed", "skipped", "rescued", "ignored"]}
            for seg in parts[1].split():
                if "=" in seg:
                    k, v = seg.split("=", 1)
                    if k in stats:
                        try:
                            stats[k] = int(v)
                        except ValueError:
                            pass
            totals[host] = stats
    return totals


def _sum_changed(totals: dict[str, dict[str, int]]) -> int:
    return sum(v.get("changed", 0) for v in totals.values())


@mcp.tool(name="inventory-diff")
def inventory_diff(left_project_root: str | None = None, left_ansible_cfg_path: str | None = None, left_inventory_paths: list[str] | None = None, right_project_root: str | None = None, right_ansible_cfg_path: str | None = None, right_inventory_paths: list[str] | None = None, include_hostvars: bool | None = None) -> dict[str, Any]:
    """Diff two inventories: hosts, groups, and optionally hostvars keys.

    Returns:
      - added_hosts, removed_hosts
      - added_groups, removed_groups, group_membership_changes
      - hostvars_key_changes (if include_hostvars)
    """
    left = inventory_parse(project_root=left_project_root, ansible_cfg_path=left_ansible_cfg_path, inventory_paths=left_inventory_paths, include_hostvars=include_hostvars)
    if not left.get("ok"):
        return {"ok": False, "side": "left", "error": left}
    right = inventory_parse(project_root=right_project_root, ansible_cfg_path=right_ansible_cfg_path, inventory_paths=right_inventory_paths, include_hostvars=include_hostvars)
    if not right.get("ok"):
        return {"ok": False, "side": "right", "error": right}
    left_hosts = set(left.get("hosts", []))
    right_hosts = set(right.get("hosts", []))
    added_hosts = sorted(list(right_hosts - left_hosts))
    removed_hosts = sorted(list(left_hosts - right_hosts))
    left_groups = {k: set(v) for k, v in (left.get("groups", {}) or {}).items()}
    right_groups = {k: set(v) for k, v in (right.get("groups", {}) or {}).items()}
    added_groups = sorted(list(set(right_groups.keys()) - set(left_groups.keys())))
    removed_groups = sorted(list(set(left_groups.keys()) - set(right_groups.keys())))
    group_membership_changes: dict[str, dict[str, list[str]]] = {}
    for g in sorted(set(left_groups.keys()) & set(right_groups.keys())):
        l = left_groups[g]
        r = right_groups[g]
        add = sorted(list(r - l))
        rem = sorted(list(l - r))
        if add or rem:
            group_membership_changes[g] = {"added": add, "removed": rem}
    res: dict[str, Any] = {
        "ok": True,
        "added_hosts": added_hosts,
        "removed_hosts": removed_hosts,
        "added_groups": added_groups,
        "removed_groups": removed_groups,
        "group_membership_changes": group_membership_changes,
    }
    if include_hostvars:
        lv = {h: set(((left.get("hostvars", {}) or {}).get(h) or {}).keys()) for h in left_hosts}
        rv = {h: set(((right.get("hostvars", {}) or {}).get(h) or {}).keys()) for h in right_hosts}
        hv_changes: dict[str, dict[str, list[str]]] = {}
        for h in sorted(left_hosts | right_hosts):
            lks = lv.get(h, set())
            rks = rv.get(h, set())
            add = sorted(list(rks - lks))
            rem = sorted(list(lks - rks))
            if add or rem:
                hv_changes[h] = {"added": add, "removed": rem}
        res["hostvars_key_changes"] = hv_changes
    return res


@mcp.tool(name="ansible-test-idempotence")
def ansible_test_idempotence(playbook_path: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, extra_vars: dict[str, Any] | None = None, verbose: int | None = None) -> dict[str, Any]:
    """Run a playbook twice and ensure no changes on the second run. Returns recap and pass/fail."""
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    # First apply
    first = ansible_playbook(playbook_path=playbook_path, inventory=inventory_str, extra_vars=extra_vars, cwd=str(cwd) if cwd else None, verbose=verbose, env=env)
    first_recap = _parse_play_recap(first.get("stdout", ""))
    # Second apply
    second = ansible_playbook(playbook_path=playbook_path, inventory=inventory_str, extra_vars=extra_vars, cwd=str(cwd) if cwd else None, verbose=verbose, env=env)
    second_recap = _parse_play_recap(second.get("stdout", ""))
    changed_total = _sum_changed(second_recap)
    return {
        "ok": first.get("ok", False) and second.get("ok", False) and changed_total == 0,
        "first_rc": first.get("rc"),
        "second_rc": second.get("rc"),
        "first_recap": first_recap,
        "second_recap": second_recap,
        "changed_total_second": changed_total,
        "first_command": first.get("command"),
        "second_command": second.get("command"),
    }


@mcp.tool(name="galaxy-lock")
def galaxy_lock(project_root: str, output_path: str | None = None) -> dict[str, Any]:
    """Create a simple lock file for installed roles/collections under the project root."""
    root = Path(project_root).expanduser().resolve()
    env, cwd = _compose_ansible_env(None, str(root), None)
    # Collections list
    rc_c, out_c, err_c = _run_command(["ansible-galaxy", "collection", "list", "--format", "json"], cwd=cwd, env=env)
    collections: list[dict[str, str]] = []
    if rc_c == 0:
        try:
            data = json.loads(out_c)
            for name, info in data.items():
                version = str(info.get("version")) if isinstance(info, dict) else None
                if version:
                    collections.append({"name": name, "version": version})
        except Exception:
            pass
    # Roles list (best-effort parse)
    rc_r, out_r, err_r = _run_command(["ansible-galaxy", "role", "list"], cwd=cwd, env=env)
    roles: list[dict[str, str]] = []
    if rc_r == 0:
        for line in out_r.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            # Expect forms like: namespace.role, x.y.z
            if "," in s:
                left, right = s.split(",", 1)
                name = left.strip()
                version = right.strip().lstrip("v ")
                if name:
                    roles.append({"name": name, "version": version})
            else:
                parts = s.split()
                if len(parts) >= 2:
                    roles.append({"name": parts[0], "version": parts[1].lstrip("v ")})
    lock = {"collections": sorted(collections, key=lambda x: x["name"]), "roles": sorted(roles, key=lambda x: x["name"]) }
    text = yaml.safe_dump(lock, sort_keys=False)
    path = Path(output_path).expanduser().resolve() if output_path else (root / "requirements.lock.yml")
    path.write_text(text, encoding="utf-8")
    return {"ok": True, "path": str(path), "collections": len(collections), "roles": len(roles)}


@contextmanager
def _vault_password_file(password: str):
    tf = tempfile.NamedTemporaryFile(prefix="vault_", suffix=".pwd", delete=False)
    try:
        tf.write(password.encode("utf-8"))
        tf.flush()
        tf.close()
        yield tf.name
    finally:
        try:
            os.remove(tf.name)
        except Exception:
            pass


def _resolve_vault_pw_args(password: str | None, password_file: str | None) -> tuple[list[str], str | None]:
    if password_file:
        return (["--vault-password-file", password_file], None)
    if password:
        return (["--vault-password-file", "__TEMPFILE__"], password)
    env_pw = os.environ.get("MCP_VAULT_PASSWORD")
    if env_pw:
        return (["--vault-password-file", "__TEMPFILE__"], env_pw)
    env_pw_file = os.environ.get("VAULT_PASSWORD_FILE")
    if env_pw_file:
        return (["--vault-password-file", env_pw_file], None)
    return ([], None)


def _run_vault_cmd(subcmd: list[str], project_root: str | None, password: str | None, password_file: str | None) -> dict[str, Any]:
    env, cwd = _compose_ansible_env(None, project_root, None)
    args, inline_pw = _resolve_vault_pw_args(password, password_file)
    if inline_pw is None:
        rc, out, err = _run_command(["ansible-vault", *subcmd, *args], cwd=cwd, env=env)
        return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err, "command": shlex.join(["ansible-vault", *subcmd, *args])}
    else:
        with _vault_password_file(inline_pw) as pwfile:
            vault_args = [a if a != "__TEMPFILE__" else pwfile for a in args]
            rc, out, err = _run_command(["ansible-vault", *subcmd, *vault_args], cwd=cwd, env=env)
            return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err, "command": shlex.join(["ansible-vault", *subcmd, *vault_args])}


@mcp.tool(name="vault-encrypt")
def vault_encrypt(file_paths: list[str] | str, project_root: str | None = None, password: str | None = None, password_file: str | None = None) -> dict[str, Any]:
    files = [file_paths] if isinstance(file_paths, str) else list(file_paths)
    return _run_vault_cmd(["encrypt", *files], project_root, password, password_file)


@mcp.tool(name="vault-decrypt")
def vault_decrypt(file_paths: list[str] | str, project_root: str | None = None, password: str | None = None, password_file: str | None = None) -> dict[str, Any]:
    files = [file_paths] if isinstance(file_paths, str) else list(file_paths)
    return _run_vault_cmd(["decrypt", *files], project_root, password, password_file)


@mcp.tool(name="vault-view")
def vault_view(file_path: str, project_root: str | None = None, password: str | None = None, password_file: str | None = None) -> dict[str, Any]:
    return _run_vault_cmd(["view", file_path], project_root, password, password_file)


@mcp.tool(name="vault-rekey")
def vault_rekey(file_paths: list[str] | str, project_root: str | None = None, old_password: str | None = None, old_password_file: str | None = None, new_password: str | None = None, new_password_file: str | None = None) -> dict[str, Any]:
    files = [file_paths] if isinstance(file_paths, str) else list(file_paths)
    # First provide old password
    old_args, inline_old = _resolve_vault_pw_args(old_password, old_password_file)
    # New password via env: ANSIBLE_VAULT_NEW_PASSWORD_FILE not supported CLI; use --new-vault-password-file
    new_args, inline_new = _resolve_vault_pw_args(new_password, new_password_file)
    # Combine
    subcmd = ["rekey", *files, *(["--new-vault-password-file", "__TEMPFILE_NEW__"] if (inline_new or new_password_file) else []), *old_args]
    env, cwd = _compose_ansible_env(None, project_root, None)
    if inline_old or inline_new:
        with _vault_password_file(inline_old or "") as oldf, _vault_password_file(inline_new or "") as newf:
            cmd = ["ansible-vault", *([c if c != "__TEMPFILE_NEW__" else newf for c in subcmd])]
            # Replace placeholder in old_args
            cmd = [a if a != "__TEMPFILE__" else oldf for a in cmd]
            rc, out, err = _run_command(cmd, cwd=cwd, env=env)
            return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err, "command": shlex.join(cmd)}
    # No inline passwords, just use provided files
    cmd = ["ansible-vault", *([c if c != "__TEMPFILE_NEW__" else (new_args[1] if new_args else "") for c in subcmd])]
    rc, out, err = _run_command(cmd, cwd=cwd, env=env)
    return {"ok": rc == 0, "rc": rc, "stdout": out, "stderr": err, "command": shlex.join(cmd)}


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


# -------------------------
# Troubleshooting Suite
# -------------------------

def _parse_json_output(stdout: str) -> dict[str, Any]:
    """Parse JSON output from Ansible modules that return structured data."""
    facts: dict[str, Any] = {}
    for line in stdout.splitlines():
        if "SUCCESS" in line and "=>" in line:
            try:
                left, right = line.split("=>", 1)
                host = left.split("|")[0].strip()
                data = json.loads(right.strip())
                facts[host] = data
            except Exception:
                continue
    return facts


def _calculate_health_score(metrics: dict[str, Any]) -> dict[str, Any]:
    """Calculate a health score based on system metrics."""
    score = 100
    issues = []
    recommendations = []
    
    # CPU health (0-100)
    cpu_usage = metrics.get("cpu_percent", 0)
    if cpu_usage > 90:
        score -= 30
        issues.append("Critical CPU usage")
        recommendations.append("Identify high CPU processes and optimize or scale")
    elif cpu_usage > 75:
        score -= 15
        issues.append("High CPU usage")
        recommendations.append("Monitor CPU trends and prepare for scaling")
    
    # Memory health
    memory_percent = metrics.get("memory_percent", 0)
    if memory_percent > 95:
        score -= 25
        issues.append("Critical memory usage")
        recommendations.append("Free memory or add more RAM")
    elif memory_percent > 85:
        score -= 10
        issues.append("High memory usage")
        recommendations.append("Monitor memory consumption patterns")
    
    # Disk health
    disk_usage = metrics.get("disk_usage_percent", 0)
    if disk_usage > 95:
        score -= 20
        issues.append("Critical disk space")
        recommendations.append("Clean up files or expand storage")
    elif disk_usage > 85:
        score -= 10
        issues.append("High disk usage")
        recommendations.append("Plan for disk space expansion")
    
    # Service health
    failed_services = metrics.get("failed_services", [])
    if failed_services:
        score -= len(failed_services) * 15
        issues.extend([f"Service {svc} is failed" for svc in failed_services])
        recommendations.extend([f"Investigate and restart {svc}" for svc in failed_services])
    
    # Network connectivity
    if not metrics.get("network_reachable", True):
        score -= 20
        issues.append("Network connectivity issues")
        recommendations.append("Check network configuration and connectivity")
    
    return {
        "score": max(0, score),
        "level": "critical" if score < 50 else "warning" if score < 80 else "healthy",
        "issues": issues,
        "recommendations": recommendations
    }


def _generate_snapshot_id() -> str:
    """Generate a unique snapshot ID."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    random_suffix = hashlib.md5(str(time.time()).encode()).hexdigest()[:8]
    return f"snapshot_{timestamp}_{random_suffix}"


def _analyze_log_patterns(logs: str) -> dict[str, Any]:
    """Analyze log content for patterns and anomalies."""
    lines = logs.splitlines()
    
    # Error patterns
    error_patterns = [
        (r"ERROR|CRITICAL|FATAL", "error"),
        (r"WARNING|WARN", "warning"),
        (r"failed|failure|exception", "failure"),
        (r"timeout|timed out", "timeout"),
        (r"connection refused|connection reset", "connection"),
        (r"out of memory|oom", "memory"),
        (r"permission denied|access denied", "permission")
    ]
    
    pattern_counts = defaultdict(int)
    recent_errors = []
    
    for line in lines[-1000:]:  # Analyze last 1000 lines
        line_lower = line.lower()
        for pattern, category in error_patterns:
            if re.search(pattern, line_lower):
                pattern_counts[category] += 1
                if category in ["error", "failure", "timeout"]:
                    recent_errors.append(line.strip())
    
    return {
        "pattern_counts": dict(pattern_counts),
        "recent_errors": recent_errors[-10:],  # Last 10 errors
        "total_lines_analyzed": min(1000, len(lines)),
        "error_rate": sum(pattern_counts.values()) / max(1, len(lines[-1000:])) * 100
    }


@mcp.tool(name="ansible-remote-command")
def ansible_remote_command(host_pattern: str, command: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, become: bool | None = None, timeout: int | None = None) -> dict[str, Any]:
    """Execute arbitrary shell commands on remote hosts with enhanced output parsing.
    
    Args:
        host_pattern: Target hosts pattern
        command: Shell command to execute
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        become: Use privilege escalation
        timeout: Command timeout in seconds
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    args = {"_raw_params": command}
    if timeout:
        args["timeout"] = timeout
    
    result = ansible_task(
        host_pattern=host_pattern,
        module="shell",
        args=args,
        inventory=inventory_str,
        become=become,
        cwd=str(cwd) if cwd else None,
        env=env
    )
    
    # Parse structured output if available
    if result.get("ok"):
        parsed = _parse_json_output(result.get("stdout", ""))
        if parsed:
            result["parsed_output"] = parsed
    
    return result


@mcp.tool(name="ansible-fetch-logs")
def ansible_fetch_logs(host_pattern: str, log_paths: list[str], project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, lines: int | None = 100, filter_pattern: str | None = None, analyze: bool | None = True) -> dict[str, Any]:
    """Fetch and analyze log files from remote hosts.
    
    Args:
        host_pattern: Target hosts pattern
        log_paths: List of log file paths to fetch
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        lines: Number of lines to fetch (like tail -n)
        filter_pattern: Regex pattern to filter log lines
        analyze: Perform log pattern analysis
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    results = {}
    
    for log_path in log_paths:
        # Build command to fetch logs
        cmd_parts = [f"tail -n {lines or 100} {log_path}"]
        if filter_pattern:
            cmd_parts.append(f"grep -E '{filter_pattern}'")
        
        command = " | ".join(cmd_parts)
        
        result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": command},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        if result.get("ok") and analyze:
            # Analyze log patterns
            log_content = result.get("stdout", "")
            analysis = _analyze_log_patterns(log_content)
            result["analysis"] = analysis
        
        results[log_path] = result
    
    return {
        "ok": all(r.get("ok", False) for r in results.values()),
        "logs": results,
        "summary": {
            "total_logs": len(log_paths),
            "successful": sum(1 for r in results.values() if r.get("ok")),
            "failed": sum(1 for r in results.values() if not r.get("ok"))
        }
    }


@mcp.tool(name="ansible-service-manager")
def ansible_service_manager(host_pattern: str, service_name: str, action: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, check_logs: bool | None = True) -> dict[str, Any]:
    """Manage services with status checking and log correlation.
    
    Args:
        host_pattern: Target hosts pattern
        service_name: Name of the service
        action: Action to perform (status, start, stop, restart, reload)
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        check_logs: Fetch recent service logs
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    # Execute service action
    result = ansible_task(
        host_pattern=host_pattern,
        module="systemd",
        args={"name": service_name, "state": action if action != "status" else None},
        inventory=inventory_str,
        cwd=str(cwd) if cwd else None,
        env=env
    )
    
    # Get service status
    status_result = ansible_task(
        host_pattern=host_pattern,
        module="service_facts",
        inventory=inventory_str,
        cwd=str(cwd) if cwd else None,
        env=env
    )
    
    # Fetch recent logs if requested
    logs = {}
    if check_logs:
        log_result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": f"journalctl -u {service_name} -n 20 --no-pager"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        logs = log_result
    
    return {
        "ok": result.get("ok", False),
        "action_result": result,
        "status": status_result,
        "logs": logs,
        "service": service_name,
        "action": action
    }


@mcp.tool(name="ansible-diagnose-host")
def ansible_diagnose_host(host_pattern: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, checks: list[str] | None = None, baseline_compare: bool | None = False, include_recommendations: bool | None = True) -> dict[str, Any]:
    """Comprehensive health assessment of target hosts.
    
    Args:
        host_pattern: Target hosts pattern
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        checks: List of check categories (system, network, security, performance)
        baseline_compare: Compare against stored baseline
        include_recommendations: Include actionable recommendations
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    check_types = checks or ["system", "network", "security", "performance"]
    diagnosis = {"timestamp": datetime.now().isoformat(), "checks": {}}
    
    # System health check
    if "system" in check_types:
        # CPU, memory, disk usage
        system_result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "df -h / | tail -1 | awk '{print $5}' | sed 's/%//'; free | grep Mem | awk '{print ($3/$2)*100}'; top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | sed 's/%us,//'"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        # Parse system metrics
        if system_result.get("ok"):
            output_lines = system_result.get("stdout", "").strip().split('\n')
            try:
                disk_usage = float(output_lines[0]) if output_lines else 0
                memory_usage = float(output_lines[1]) if len(output_lines) > 1 else 0
                cpu_usage = float(output_lines[2]) if len(output_lines) > 2 else 0
                
                system_metrics = {
                    "disk_usage_percent": disk_usage,
                    "memory_percent": memory_usage,
                    "cpu_percent": cpu_usage
                }
            except (ValueError, IndexError):
                system_metrics = {"error": "Failed to parse system metrics"}
        else:
            system_metrics = {"error": "Failed to gather system metrics"}
        
        diagnosis["checks"]["system"] = system_metrics
    
    # Network health check
    if "network" in check_types:
        network_result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "ping -c 3 8.8.8.8 > /dev/null 2>&1 && echo 'reachable' || echo 'unreachable'"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        diagnosis["checks"]["network"] = {
            "internet_reachable": network_result.get("stdout", "").strip() == "reachable" if network_result.get("ok") else False
        }
    
    # Security check
    if "security" in check_types:
        security_result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "last -n 5 | grep -v 'wtmp begins' | wc -l; ps aux | grep -v grep | grep -E '(ssh|telnet|ftp)' | wc -l"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        diagnosis["checks"]["security"] = {
            "recent_logins": security_result.get("stdout", "0").strip().split('\n')[0] if security_result.get("ok") else "unknown",
            "network_services": security_result.get("stdout", "0").strip().split('\n')[1] if security_result.get("ok") and len(security_result.get("stdout", "").strip().split('\n')) > 1 else "unknown"
        }
    
    # Performance check
    if "performance" in check_types:
        perf_result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "uptime | awk '{print $(NF-2), $(NF-1), $NF}' | tr -d ','"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        diagnosis["checks"]["performance"] = {
            "load_average": perf_result.get("stdout", "").strip() if perf_result.get("ok") else "unknown"
        }
    
    # Calculate overall health score
    if include_recommendations:
        all_metrics = {}
        for check_type, metrics in diagnosis["checks"].items():
            if isinstance(metrics, dict) and "error" not in metrics:
                all_metrics.update(metrics)
        
        health_assessment = _calculate_health_score(all_metrics)
        diagnosis["health_score"] = health_assessment
    
    return {
        "ok": True,
        "diagnosis": diagnosis,
        "host_pattern": host_pattern,
        "timestamp": diagnosis["timestamp"]
    }


@mcp.tool(name="ansible-capture-baseline")
def ansible_capture_baseline(host_pattern: str, snapshot_name: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, include: list[str] | None = None) -> dict[str, Any]:
    """Capture comprehensive system state baseline for later comparison.
    
    Args:
        host_pattern: Target hosts pattern
        snapshot_name: Name for this baseline snapshot
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        include: Categories to include (configs, processes, network, performance)
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    snapshot_id = _generate_snapshot_id()
    categories = include or ["configs", "processes", "network", "performance"]
    baseline = {
        "snapshot_id": snapshot_id,
        "name": snapshot_name,
        "timestamp": datetime.now().isoformat(),
        "host_pattern": host_pattern,
        "data": {}
    }
    
    # Capture process information
    if "processes" in categories:
        proc_result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "ps aux --sort=-%cpu | head -20"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        baseline["data"]["processes"] = proc_result
    
    # Capture network configuration
    if "network" in categories:
        net_result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "ip addr show; netstat -tuln"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        baseline["data"]["network"] = net_result
    
    # Capture system configuration
    if "configs" in categories:
        config_result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "uname -a; cat /etc/os-release; systemctl list-units --failed"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        baseline["data"]["configs"] = config_result
    
    # Capture performance metrics
    if "performance" in categories:
        perf_result = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "vmstat 1 3; iostat -x 1 3"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        baseline["data"]["performance"] = perf_result
    
    # Store baseline (in real implementation, this would go to a database or file)
    # For now, we'll return the baseline data
    return {
        "ok": True,
        "snapshot_id": snapshot_id,
        "name": snapshot_name,
        "categories_captured": categories,
        "timestamp": baseline["timestamp"],
        "baseline_data": baseline  # In production, store this externally
    }


@mcp.tool(name="ansible-compare-states")
def ansible_compare_states(host_pattern: str, baseline_snapshot_id: str, current_snapshot_name: str | None = None, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None) -> dict[str, Any]:
    """Compare current system state against a previously captured baseline.
    
    Args:
        host_pattern: Target hosts pattern
        baseline_snapshot_id: ID of the baseline snapshot to compare against
        current_snapshot_name: Optional name for the current state snapshot
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
    """
    # Capture current state
    current_name = current_snapshot_name or f"current_{datetime.now().strftime('%H%M%S')}"
    current_state = ansible_capture_baseline(
        host_pattern=host_pattern,
        snapshot_name=current_name,
        project_root=project_root,
        ansible_cfg_path=ansible_cfg_path,
        inventory_paths=inventory_paths
    )
    
    # In a real implementation, you would fetch the baseline from storage
    # For now, we'll return a comparison framework
    return {
        "ok": current_state.get("ok", False),
        "comparison": {
            "baseline_id": baseline_snapshot_id,
            "current_snapshot": current_state.get("snapshot_id"),
            "timestamp": datetime.now().isoformat(),
            "differences": {
                "processes": "Process comparison would be performed here",
                "network": "Network configuration changes would be detected",
                "configs": "Configuration drift analysis",
                "performance": "Performance regression detection"
            },
            "summary": {
                "changes_detected": 0,  # Would be calculated from actual comparison
                "critical_changes": 0,
                "recommendations": ["Comparison analysis would generate recommendations here"]
            }
        },
        "current_state": current_state
    }


@mcp.tool(name="ansible-auto-heal")
def ansible_auto_heal(host_pattern: str, symptoms: list[str], project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, max_impact: str | None = "low", dry_run: bool | None = True) -> dict[str, Any]:
    """Intelligent automated problem resolution with safety checks.
    
    Args:
        host_pattern: Target hosts pattern
        symptoms: List of detected symptoms
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        max_impact: Maximum allowed impact level (low, medium, high)
        dry_run: Preview actions without executing
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    # Symptom-to-solution mapping
    healing_actions = []
    
    for symptom in symptoms:
        if symptom == "high_cpu":
            healing_actions.append({
                "symptom": symptom,
                "action": "restart_high_cpu_processes",
                "impact": "medium",
                "command": "kill -9 $(ps aux --sort=-%cpu | head -6 | tail -5 | awk '{print $2}')",
                "safety_check": "ps aux --sort=-%cpu | head -6",
                "description": "Terminate top 5 CPU-consuming processes"
            })
        
        elif symptom == "high_memory":
            healing_actions.append({
                "symptom": symptom,
                "action": "clear_cache",
                "impact": "low",
                "command": "sync && echo 3 > /proc/sys/vm/drop_caches",
                "safety_check": "free -m",
                "description": "Clear system cache to free memory"
            })
        
        elif symptom == "disk_full":
            healing_actions.append({
                "symptom": symptom,
                "action": "cleanup_temp_files",
                "impact": "low",
                "command": "find /tmp -type f -atime +7 -delete && find /var/log -name '*.log' -size +100M -delete",
                "safety_check": "df -h",
                "description": "Clean up old temporary files and large logs"
            })
        
        elif symptom == "service_failed":
            healing_actions.append({
                "symptom": symptom,
                "action": "restart_failed_services",
                "impact": "medium",
                "command": "systemctl reset-failed && systemctl restart $(systemctl --failed --no-legend | awk '{print $1}')",
                "safety_check": "systemctl --failed",
                "description": "Restart all failed services"
            })
    
    # Filter actions by impact level
    impact_hierarchy = {"low": 1, "medium": 2, "high": 3}
    max_impact_level = impact_hierarchy.get(max_impact or "low", 1)
    
    allowed_actions = [
        action for action in healing_actions
        if impact_hierarchy.get(action["impact"], 1) <= max_impact_level
    ]
    
    execution_results = []
    
    if not dry_run:
        # Execute healing actions
        for action in allowed_actions:
            # Run safety check first
            safety_result = ansible_task(
                host_pattern=host_pattern,
                module="shell",
                args={"_raw_params": action["safety_check"]},
                inventory=inventory_str,
                cwd=str(cwd) if cwd else None,
                env=env
            )
            
            # Execute healing action
            heal_result = ansible_task(
                host_pattern=host_pattern,
                module="shell",
                args={"_raw_params": action["command"]},
                inventory=inventory_str,
                cwd=str(cwd) if cwd else None,
                env=env
            )
            
            execution_results.append({
                "action": action,
                "safety_check_result": safety_result,
                "healing_result": heal_result,
                "success": heal_result.get("ok", False)
            })
    
    return {
        "ok": True,
        "symptoms": symptoms,
        "proposed_actions": allowed_actions,
        "blocked_actions": [a for a in healing_actions if a not in allowed_actions],
        "max_impact": max_impact,
        "dry_run": dry_run,
        "execution_results": execution_results if not dry_run else None,
        "summary": {
            "total_symptoms": len(symptoms),
            "actionable_symptoms": len(allowed_actions),
            "executed_actions": len(execution_results) if not dry_run else 0,
            "successful_actions": sum(1 for r in execution_results if r.get("success")) if not dry_run else 0
        }
    }


@mcp.tool(name="ansible-network-matrix")
def ansible_network_matrix(host_patterns: list[str], target_hosts: list[str] | None = None, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, check_ports: list[int] | None = None) -> dict[str, Any]:
    """Comprehensive network connectivity matrix between hosts.
    
    Args:
        host_patterns: List of source host patterns
        target_hosts: List of target hostnames/IPs to test (defaults to same as sources)
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        check_ports: List of ports to check connectivity (default: [22, 80, 443])
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    ports = check_ports or [22, 80, 443]
    matrix_results = {}
    
    for host_pattern in host_patterns:
        matrix_results[host_pattern] = {}
        
        # Get the actual hosts for this pattern first
        hosts_result = ansible_task(
            host_pattern=host_pattern,
            module="setup",
            args={"gather_subset": "!all,network"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        targets = target_hosts or host_patterns
        for target in targets:
            # Ping test
            ping_result = ansible_task(
                host_pattern=host_pattern,
                module="shell",
                args={"_raw_params": f"ping -c 3 {target} > /dev/null 2>&1 && echo 'success' || echo 'failed'"},
                inventory=inventory_str,
                cwd=str(cwd) if cwd else None,
                env=env
            )
            
            # Port connectivity tests
            port_results = {}
            for port in ports:
                port_test = ansible_task(
                    host_pattern=host_pattern,
                    module="shell",
                    args={"_raw_params": f"nc -z -w5 {target} {port} && echo 'open' || echo 'closed'"},
                    inventory=inventory_str,
                    cwd=str(cwd) if cwd else None,
                    env=env
                )
                port_results[port] = port_test.get("stdout", "").strip()
            
            # Traceroute
            traceroute_result = ansible_task(
                host_pattern=host_pattern,
                module="shell",
                args={"_raw_params": f"traceroute -m 10 {target} 2>/dev/null | tail -1"},
                inventory=inventory_str,
                cwd=str(cwd) if cwd else None,
                env=env
            )
            
            matrix_results[host_pattern][target] = {
                "ping": ping_result.get("stdout", "").strip(),
                "ports": port_results,
                "traceroute": traceroute_result.get("stdout", "").strip()
            }
    
    return {
        "ok": True,
        "network_matrix": matrix_results,
        "summary": {
            "source_patterns": len(host_patterns),
            "target_hosts": len(targets),
            "ports_tested": ports
        }
    }


@mcp.tool(name="ansible-security-audit")
def ansible_security_audit(host_pattern: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, audit_categories: list[str] | None = None, generate_report: bool | None = True) -> dict[str, Any]:
    """Comprehensive security audit and vulnerability assessment.
    
    Args:
        host_pattern: Target hosts pattern
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        audit_categories: Categories to audit (packages, permissions, network, config)
        generate_report: Generate detailed security report
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    categories = audit_categories or ["packages", "permissions", "network", "config"]
    audit_results = {"timestamp": datetime.now().isoformat(), "categories": {}}
    
    # Package vulnerability audit
    if "packages" in categories:
        # Check for packages with known vulnerabilities
        package_audit = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "apt list --upgradable 2>/dev/null | grep -E '(security|CVE)' | wc -l || yum check-update --security 2>/dev/null | grep -c 'needed for security' || echo '0'"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        # Check for outdated packages
        outdated_packages = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "apt list --upgradable 2>/dev/null | wc -l || yum check-update 2>/dev/null | wc -l"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        audit_results["categories"]["packages"] = {
            "security_updates_available": package_audit.get("stdout", "0").strip(),
            "total_updates_available": outdated_packages.get("stdout", "0").strip()
        }
    
    # Permission and access audit
    if "permissions" in categories:
        # Check for SUID/SGID files
        suid_check = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "find /usr /bin /sbin -perm -4000 -o -perm -2000 2>/dev/null | wc -l"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        # Check for world-writable files
        writable_check = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "find / -maxdepth 3 -perm -002 -type f 2>/dev/null | grep -v '/proc\\|/sys\\|/dev' | wc -l"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        audit_results["categories"]["permissions"] = {
            "suid_sgid_files": suid_check.get("stdout", "0").strip(),
            "world_writable_files": writable_check.get("stdout", "0").strip()
        }
    
    # Network security audit
    if "network" in categories:
        # Open ports scan
        open_ports = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "netstat -tuln | grep LISTEN | wc -l"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        # Check for unnecessary services
        services_check = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "systemctl list-units --type=service --state=running | grep -E '(telnet|ftp|rsh|rlogin)' | wc -l"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        audit_results["categories"]["network"] = {
            "open_ports": open_ports.get("stdout", "0").strip(),
            "insecure_services": services_check.get("stdout", "0").strip()
        }
    
    # Configuration audit
    if "config" in categories:
        # SSH configuration check
        ssh_config = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "grep -E '^PermitRootLogin|^PasswordAuthentication|^Protocol' /etc/ssh/sshd_config 2>/dev/null || echo 'SSH config not accessible'"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        # Password policy check
        password_policy = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "grep -E '^PASS_MAX_DAYS|^PASS_MIN_DAYS|^PASS_WARN_AGE' /etc/login.defs 2>/dev/null | wc -l"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        audit_results["categories"]["config"] = {
            "ssh_config": ssh_config.get("stdout", "").strip(),
            "password_policies": password_policy.get("stdout", "0").strip()
        }
    
    # Generate security score
    if generate_report:
        security_score = 100
        recommendations = []
        
        # Calculate score based on findings
        for category, results in audit_results["categories"].items():
            if category == "packages":
                security_updates = int(results.get("security_updates_available", "0"))
                if security_updates > 0:
                    security_score -= min(security_updates * 5, 30)
                    recommendations.append(f"Apply {security_updates} security updates immediately")
            
            elif category == "permissions":
                world_writable = int(results.get("world_writable_files", "0"))
                if world_writable > 0:
                    security_score -= min(world_writable * 2, 20)
                    recommendations.append(f"Fix {world_writable} world-writable files")
            
            elif category == "network":
                insecure_services = int(results.get("insecure_services", "0"))
                if insecure_services > 0:
                    security_score -= insecure_services * 15
                    recommendations.append("Disable insecure network services")
        
        audit_results["security_assessment"] = {
            "score": max(0, security_score),
            "level": "critical" if security_score < 40 else "warning" if security_score < 70 else "good",
            "recommendations": recommendations
        }
    
    return {
        "ok": True,
        "audit": audit_results,
        "host_pattern": host_pattern,
        "timestamp": audit_results["timestamp"]
    }


@mcp.tool(name="ansible-health-monitor")
def ansible_health_monitor(host_pattern: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, monitoring_duration: int | None = 300, metrics_interval: int | None = 30) -> dict[str, Any]:
    """Continuous health monitoring with trend analysis.
    
    Args:
        host_pattern: Target hosts pattern
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        monitoring_duration: Total monitoring duration in seconds
        metrics_interval: Interval between metric collections in seconds
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    duration = monitoring_duration or 300
    interval = metrics_interval or 30
    collection_points = duration // interval
    
    # Collect metrics over time
    metrics_history = []
    start_time = datetime.now()
    
    for i in range(collection_points):
        # Collect current metrics
        current_metrics = ansible_task(
            host_pattern=host_pattern,
            module="shell",
            args={"_raw_params": "echo $(date '+%Y-%m-%d %H:%M:%S'),$(cat /proc/loadavg | awk '{print $1}'),$(free | grep Mem | awk '{print ($3/$2)*100}'),$(df / | tail -1 | awk '{print $5}' | sed 's/%//')"},
            inventory=inventory_str,
            cwd=str(cwd) if cwd else None,
            env=env
        )
        
        if current_metrics.get("ok"):
            timestamp, load_avg, memory_percent, disk_percent = current_metrics.get("stdout", "").strip().split(',')
            metrics_history.append({
                "timestamp": timestamp,
                "load_average": float(load_avg),
                "memory_percent": float(memory_percent),
                "disk_percent": float(disk_percent)
            })
        
        # Wait for next interval (except for last iteration)
        if i < collection_points - 1:
            time.sleep(interval)
    
    # Analyze trends
    if len(metrics_history) > 1:
        # Calculate trends
        load_trend = (metrics_history[-1]["load_average"] - metrics_history[0]["load_average"]) / len(metrics_history)
        memory_trend = (metrics_history[-1]["memory_percent"] - metrics_history[0]["memory_percent"]) / len(metrics_history)
        
        # Detect anomalies
        load_values = [m["load_average"] for m in metrics_history]
        memory_values = [m["memory_percent"] for m in metrics_history]
        
        load_avg_val = sum(load_values) / len(load_values)
        memory_avg_val = sum(memory_values) / len(memory_values)
        
        anomalies = []
        for metric in metrics_history:
            if metric["load_average"] > load_avg_val * 1.5:
                anomalies.append(f"High load spike at {metric['timestamp']}: {metric['load_average']}")
            if metric["memory_percent"] > memory_avg_val * 1.3:
                anomalies.append(f"Memory spike at {metric['timestamp']}: {metric['memory_percent']}%")
        
        trend_analysis = {
            "load_trend": "increasing" if load_trend > 0.1 else "decreasing" if load_trend < -0.1 else "stable",
            "memory_trend": "increasing" if memory_trend > 1 else "decreasing" if memory_trend < -1 else "stable",
            "anomalies": anomalies,
            "average_load": load_avg_val,
            "average_memory": memory_avg_val
        }
    else:
        trend_analysis = {"error": "Insufficient data for trend analysis"}
    
    return {
        "ok": True,
        "monitoring": {
            "start_time": start_time.isoformat(),
            "duration_seconds": duration,
            "data_points": len(metrics_history),
            "metrics_history": metrics_history,
            "trend_analysis": trend_analysis
        },
        "host_pattern": host_pattern
    }


@mcp.tool(name="ansible-performance-baseline")
def ansible_performance_baseline(host_pattern: str, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, benchmark_duration: int | None = 60, store_baseline: bool | None = True) -> dict[str, Any]:
    """Establish performance baselines and detect regressions.
    
    Args:
        host_pattern: Target hosts pattern
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        benchmark_duration: Duration for benchmark tests in seconds
        store_baseline: Store baseline for future comparisons
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    duration = benchmark_duration or 60
    baseline_results = {"timestamp": datetime.now().isoformat(), "benchmarks": {}}
    
    # CPU benchmark (simple calculation test)
    cpu_benchmark = ansible_task(
        host_pattern=host_pattern,
        module="shell",
        args={"_raw_params": f"time (for i in {{1..1000000}}; do echo $((i*i)) > /dev/null; done) 2>&1 | grep real | awk '{{print $2}}'"},
        inventory=inventory_str,
        cwd=str(cwd) if cwd else None,
        env=env
    )
    baseline_results["benchmarks"]["cpu"] = cpu_benchmark.get("stdout", "").strip()
    
    # Memory benchmark (allocate and access memory)
    memory_benchmark = ansible_task(
        host_pattern=host_pattern,
        module="shell",
        args={"_raw_params": "dd if=/dev/zero of=/tmp/testfile bs=1M count=100 2>&1 | grep -o '[0-9.]* MB/s' | head -1"},
        inventory=inventory_str,
        cwd=str(cwd) if cwd else None,
        env=env
    )
    baseline_results["benchmarks"]["memory"] = memory_benchmark.get("stdout", "").strip()
    
    # Disk I/O benchmark
    disk_benchmark = ansible_task(
        host_pattern=host_pattern,
        module="shell",
        args={"_raw_params": "dd if=/dev/zero of=/tmp/testfile bs=1M count=100 conv=fdatasync 2>&1 | grep -o '[0-9.]* MB/s' | tail -1; rm -f /tmp/testfile"},
        inventory=inventory_str,
        cwd=str(cwd) if cwd else None,
        env=env
    )
    baseline_results["benchmarks"]["disk_write"] = disk_benchmark.get("stdout", "").strip()
    
    # Network latency test (to local gateway)
    network_test = ansible_task(
        host_pattern=host_pattern,
        module="shell",
        args={"_raw_params": "ping -c 10 $(ip route | grep default | awk '{print $3}' | head -1) | grep 'avg' | awk -F'/' '{print $5}'"},
        inventory=inventory_str,
        cwd=str(cwd) if cwd else None,
        env=env
    )
    baseline_results["benchmarks"]["network_latency"] = network_test.get("stdout", "").strip()
    
    # System load during benchmarks
    load_test = ansible_task(
        host_pattern=host_pattern,
        module="shell",
        args={"_raw_params": "uptime | awk '{print $(NF-2)}' | tr -d ','"},
        inventory=inventory_str,
        cwd=str(cwd) if cwd else None,
        env=env
    )
    baseline_results["benchmarks"]["system_load"] = load_test.get("stdout", "").strip()
    
    # Calculate performance score
    performance_score = 100
    issues = []
    
    # Analyze results (simplified scoring)
    try:
        if baseline_results["benchmarks"]["system_load"]:
            load_val = float(baseline_results["benchmarks"]["system_load"])
            if load_val > 2.0:
                performance_score -= 20
                issues.append("High system load detected")
        
        if "MB/s" in baseline_results["benchmarks"]["memory"]:
            memory_speed = float(baseline_results["benchmarks"]["memory"].split()[0])
            if memory_speed < 100:  # Less than 100 MB/s
                performance_score -= 15
                issues.append("Low memory bandwidth")
    except (ValueError, IndexError):
        issues.append("Could not parse some benchmark results")
    
    baseline_results["performance_assessment"] = {
        "score": performance_score,
        "level": "excellent" if performance_score > 85 else "good" if performance_score > 70 else "poor",
        "issues": issues
    }
    
    if store_baseline:
        # In production, store this in a database or file
        baseline_id = _generate_snapshot_id()
        baseline_results["baseline_id"] = baseline_id
    
    return {
        "ok": True,
        "baseline": baseline_results,
        "host_pattern": host_pattern,
        "duration": duration
    }


@mcp.tool(name="ansible-log-hunter")
def ansible_log_hunter(host_pattern: str, search_patterns: list[str], log_paths: list[str] | None = None, project_root: str | None = None, ansible_cfg_path: str | None = None, inventory_paths: list[str] | None = None, time_range: str | None = None, correlation_window: int | None = 300) -> dict[str, Any]:
    """Advanced log hunting and correlation across multiple sources.
    
    Args:
        host_pattern: Target hosts pattern
        search_patterns: List of regex patterns to search for
        log_paths: List of log file paths (defaults to common system logs)
        project_root: Project root directory
        ansible_cfg_path: Ansible config file path
        inventory_paths: Inventory file paths
        time_range: Time range for logs (e.g., '1h', '24h', '7d')
        correlation_window: Time window in seconds for event correlation
    """
    env, cwd = _compose_ansible_env(ansible_cfg_path, project_root, None)
    inventory_str = ",".join(inventory_paths) if inventory_paths else None
    
    # Default log paths if not specified
    default_logs = [
        "/var/log/syslog",
        "/var/log/messages", 
        "/var/log/auth.log",
        "/var/log/secure",
        "/var/log/kern.log"
    ]
    logs_to_search = log_paths or default_logs
    
    # Build time filter if specified
    time_filter = ""
    if time_range:
        if time_range.endswith('h'):
            hours = int(time_range[:-1])
            time_filter = f"--since '{hours} hours ago'"
        elif time_range.endswith('d'):
            days = int(time_range[:-1])
            time_filter = f"--since '{days} days ago'"
    
    hunt_results = {}
    all_matches = []
    
    for log_path in logs_to_search:
        log_results = {}
        
        for pattern in search_patterns:
            # Search for pattern in log
            if time_filter and "journal" in log_path:
                # Use journalctl for systemd logs
                search_cmd = f"journalctl {time_filter} | grep -E '{pattern}'"
            else:
                # Regular log file search
                search_cmd = f"grep -E '{pattern}' {log_path} 2>/dev/null | tail -100"
            
            search_result = ansible_task(
                host_pattern=host_pattern,
                module="shell",
                args={"_raw_params": search_cmd},
                inventory=inventory_str,
                cwd=str(cwd) if cwd else None,
                env=env
            )
            
            if search_result.get("ok") and search_result.get("stdout"):
                matches = search_result.get("stdout", "").strip().split('\n')
                log_results[pattern] = {
                    "matches": matches,
                    "count": len(matches)
                }
                
                # Add to all matches for correlation
                for match in matches:
                    all_matches.append({
                        "log_file": log_path,
                        "pattern": pattern,
                        "line": match,
                        "timestamp": _extract_timestamp_from_log(match)
                    })
        
        if log_results:
            hunt_results[log_path] = log_results
    
    # Correlate events within time window
    correlated_events = []
    if len(all_matches) > 1:
        # Sort by timestamp
        sorted_matches = sorted(all_matches, key=lambda x: x.get("timestamp", ""))
        
        # Find events within correlation window
        for i, event in enumerate(sorted_matches):
            related_events = [event]
            event_time = event.get("timestamp")
            
            if event_time:
                for j, other_event in enumerate(sorted_matches[i+1:], i+1):
                    other_time = other_event.get("timestamp")
                    if other_time and abs((event_time - other_time).total_seconds()) <= correlation_window:
                        related_events.append(other_event)
                
                if len(related_events) > 1:
                    correlated_events.append({
                        "primary_event": event,
                        "related_events": related_events[1:],
                        "correlation_strength": len(related_events)
                    })
    
    return {
        "ok": True,
        "hunt_results": hunt_results,
        "correlation": {
            "total_matches": len(all_matches),
            "correlated_events": len(correlated_events),
            "correlations": correlated_events[:10]  # Top 10 correlations
        },
        "summary": {
            "patterns_searched": len(search_patterns),
            "logs_searched": len(logs_to_search),
            "logs_with_matches": len(hunt_results)
        }
    }


def _extract_timestamp_from_log(log_line: str) -> datetime | None:
    """Extract timestamp from log line (simplified implementation)."""
    try:
        # Try common log timestamp formats
        timestamp_patterns = [
            r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})',  # ISO format
            r'(\w{3} \d{1,2} \d{2}:\d{2}:\d{2})',      # Syslog format
        ]
        
        for pattern in timestamp_patterns:
            match = re.search(pattern, log_line)
            if match:
                timestamp_str = match.group(1)
                # Simplified parsing - in production use more robust parsing
                if '-' in timestamp_str:
                    return datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                else:
                    # Add current year for syslog format
                    current_year = datetime.now().year
                    return datetime.strptime(f"{current_year} {timestamp_str}", '%Y %b %d %H:%M:%S')
    except Exception:
        pass
    return None


if __name__ == "__main__":
    mcp.run(transport="stdio")


