MCP Ansible Server

Advanced Ansible Model Context Protocol (MCP) server in Python exposing Ansible utilities for inventories, playbooks, roles, and project workflows.

Quick start

```bash
git clone https://github.com/bsahane/mcp-ansible.git
cd mcp-ansible

# Create and activate Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies via requirements.txt
python -m pip install -U pip
pip install -r requirements.txt

# (Optional) install the project package locally
pip install -e .

# Run the MCP server
python src/ansible_mcp/server.py
```

Requirements

- Python 3.10+
- macOS/Linux

Setup

```bash
cd /Users/bsahane/Developer/cursor/mcp-ansible
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install "mcp[cli]>=1.2.0" "PyYAML>=6.0.1" "ansible-core>=2.16.0"
pip install -e .
```

Run the server

```bash
python src/ansible_mcp/server.py
```

Cursor config (`/Users/bsahane/.cursor/mcp.json`)

```json
{
  "mcpServers": {
    "ansible-mcp": {
      "command": "python",
      "args": [
        "/Users/bsahane/Developer/cursor/mcp-ansible/src/ansible_mcp/server.py"
      ],
      "env": {
        "MCP_ANSIBLE_PROJECT_ROOT": "/Users/bsahane/GitLab/projectAIOPS/mcp-ansible-server",
        "MCP_ANSIBLE_INVENTORY": "/Users/bsahane/GitLab/projectAIOPS/mcp-ansible-server/inventory/hosts.ini",
        "MCP_ANSIBLE_PROJECT_NAME": "projectAIOPS"
      }
    }
  }
}
```

Claude for Desktop config

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ansible-mcp": {
      "command": "python",
      "args": [
        "/Users/bsahane/Developer/cursor/mcp-ansible/src/ansible_mcp/server.py"
      ],
      "env": {
        "MCP_ANSIBLE_PROJECT_ROOT": "/Users/bsahane/GitLab/projectAIOPS/mcp-ansible-server",
        "MCP_ANSIBLE_INVENTORY": "/Users/bsahane/GitLab/projectAIOPS/mcp-ansible-server/inventory/hosts.ini",
        "MCP_ANSIBLE_PROJECT_NAME": "projectAIOPS"
      }
    }
  }
}
```

Tools (names)

- create-playbook: Create playbooks from YAML strings or dicts
- validate-playbook: Validate playbook syntax (ansible-playbook --syntax-check)
- ansible-playbook: Execute playbooks
- ansible-task: Run ad-hoc tasks (defaults to connection=local for localhost)
- ansible-role: Execute roles via generated temporary playbook
- create-role-structure: Scaffold role directory tree
- ansible-inventory: List inventory hosts and groups
- register-project: Register an Ansible project for easy reuse
- list-projects: Show registered projects and default
- project-playbooks: Discover playbooks under a project root
- project-run-playbook: Run a playbook using a registered project’s inventory/env

Local inventory suite (no AAP/AWX)

- inventory-parse: Parse inventories (ansible.cfg-aware), return hosts/groups/hostvars
- inventory-graph: Show group/host graph
- inventory-find-host: Show a host’s groups and merged vars
- ansible-ping: Ad-hoc ping module
- ansible-gather-facts: Run setup and return parsed facts
- validate-yaml: Validate YAML files with error locations
- galaxy-install: Install roles/collections from requirements
- project-bootstrap: Galaxy install + env inspection

Environment variables (optional)

- MCP_ANSIBLE_PROJECT_ROOT: absolute project root
- MCP_ANSIBLE_INVENTORY: inventory path or directory
- MCP_ANSIBLE_PROJECT_NAME: label for env project
- MCP_ANSIBLE_ROLES_PATH: colon-separated roles paths
- MCP_ANSIBLE_COLLECTIONS_PATHS: colon-separated collections paths
- MCP_ANSIBLE_ENV_<KEY>: forwarded to process env (e.g., MCP_ANSIBLE_ENV_ANSIBLE_CONFIG)

Examples (Claude Tools)

- List hosts from inventory:
  - Tool: ansible-inventory
  - Args: inventory = "/Users/bsahane/GitLab/projectAIOPS/mcp-ansible-server/inventory/hosts.ini"

- Run a simple playbook:
  - Tool: ansible-playbook
  - Args:
    - playbook_path: absolute path to playbook.yml
    - inventory: "/Users/bsahane/GitLab/projectAIOPS/mcp-ansible-server/inventory/hosts.ini"

- Ad-hoc ping localhost:
  - Tool: ansible-task
  - Args:
    - host_pattern: "localhost"
    - module: "ping"
    - inventory: "localhost,"

- Scaffold a role:
  - Tool: create-role-structure
  - Args:
    - base_path: "/tmp"
    - role_name: "demo_role"

- Register a project and run a project playbook:
  - Tool: register-project
    - name: "projectAIOPS"
    - root: "/Users/bsahane/GitLab/projectAIOPS/mcp-ansible-server"
    - inventory: "/Users/bsahane/GitLab/projectAIOPS/mcp-ansible-server/inventory/hosts.ini"
    - make_default: true
  - Tool: project-playbooks
    - project: "projectAIOPS"
  - Tool: project-run-playbook
    - playbook_path: absolute path from discovered list

Examples for local inventory suite

- Parse via ansible.cfg with multiple inventories (merges group_vars/host_vars):
  - Tool: inventory-parse
  - Args:
    - ansible_cfg_path: "/abs/path/to/ansible.cfg"
    - include_hostvars: true

- Parse a specific extensionless inventory file:
  - Tool: inventory-parse
  - Args:
    - project_root: "/abs/path/to/project"
    - inventory_paths: ["/abs/path/to/project/inventories/stage/inventory"]
    - include_hostvars: true

- Ping a group from inventory:
  - Tool: ansible-ping
  - Args:
    - project_root: "/abs/path/to/project"
    - host_pattern: "aws_mx_ext_stage"

Notes

- The server uses stdio transport. Do not print to stdout; logs go to stderr.
- Ansible connection/auth follows your local Ansible configuration.

Reference

- MCP Quickstart (Python): https://modelcontextprotocol.io/quickstart/server#python


### Tool reference (detailed)

Below are all tools with short descriptions, minimal args, an example question you can ask in the MCP UI, and a sample answer.

- **create-playbook**: Create an Ansible playbook file from YAML string or object
  - Minimal args:
    ```json
    { "playbook": [{"hosts":"all","tasks":[{"debug":{"msg":"hi"}}]}] }
    ```
  - Example question: "Create a playbook that prints hello for all hosts."
  - Possible answer: `{ "path": "/tmp/playbook_x.yml", "bytes_written": 123, "preview": "- hosts: all..." }`

- **validate-playbook**: Syntax check a playbook
  - Minimal args:
    ```json
    { "playbook_path": "/abs/playbook.yml" }
    ```
  - Example question: "Is this playbook syntactically valid?"
  - Possible answer: `{ "ok": true, "rc": 0 }`

- **ansible-playbook**: Run a playbook
  - Minimal args:
    ```json
    { "playbook_path": "/abs/playbook.yml", "inventory": "localhost," }
    ```
  - Example question: "Run this playbook against localhost."
  - Possible answer: `{ "ok": true, "rc": 0, "stdout": "PLAY [all]..." }`

- **ansible-task**: Run an ad‑hoc module
  - Minimal args:
    ```json
    { "host_pattern": "localhost", "module": "ping", "inventory": "localhost," }
    ```
  - Example question: "Ping localhost."
  - Possible answer: `{ "ok": true, "stdout": "pong" }`

- **ansible-role**: Execute a role via a temporary playbook
  - Minimal args:
    ```json
    { "role_name": "myrole", "hosts": "localhost", "inventory": "localhost," }
    ```
  - Example question: "Run role myrole on localhost."
  - Possible answer: `{ "ok": true, "rc": 0 }`

- **create-role-structure**: Scaffold a role directory tree
  - Minimal args:
    ```json
    { "base_path": "/tmp", "role_name": "demo" }
    ```
  - Example question: "Create an Ansible role skeleton named demo."
  - Possible answer: `{ "created": [".../tasks/main.yml", ...], "role_path": "/tmp/demo" }`

- **ansible-inventory**: List hosts and groups from an inventory
  - Minimal args:
    ```json
    { "inventory": "/abs/inventory" }
    ```
  - Example question: "List hosts in this inventory."
  - Possible answer: `{ "hosts": ["host01"], "groups": {"web": ["host01"]} }`

- **register-project**: Register an Ansible project for reuse
  - Minimal args:
    ```json
    { "name": "proj", "root": "/abs/project", "make_default": true }
    ```
  - Example question: "Register my project root and make it default."
  - Possible answer: `{ "path": "~/.config/mcp-ansible/config.json", "projects": ["proj"] }`

- **list-projects**: Show registered projects
  - Minimal args: `{}`
  - Example question: "What projects are registered and which is default?"
  - Possible answer: `{ "default": "proj", "projects": {"proj": {"root": "/abs"}} }`

- **project-playbooks**: Discover playbooks under a project root
  - Minimal args:
    ```json
    { "project": "proj" }
    ```
  - Example question: "List playbooks in my project."
  - Possible answer: `{ "ok": true, "playbooks": ["/abs/x.yml", "/abs/y.yml"] }`

- **project-run-playbook**: Run a playbook using project inventory/env
  - Minimal args:
    ```json
    { "playbook_path": "/abs/x.yml", "project": "proj" }
    ```
  - Example question: "Run x.yml in my default project."
  - Possible answer: `{ "ok": true, "rc": 0 }`

- **inventory-parse**: Parse inventories (ansible.cfg aware, merges group_vars/host_vars)
  - Minimal args:
    ```json
    { "project_root": "/abs/project", "include_hostvars": true }
    ```
  - Example question: "Resolve all hosts and vars from my project root."
  - Possible answer: `{ "hosts": ["h1"], "groups": {"web":["h1"]}, "hostvars": {"h1": {...}} }`

- **inventory-graph**: Show inventory graph
  - Minimal args:
    ```json
    { "project_root": "/abs/project" }
    ```
  - Example question: "Show the inventory graph."
  - Possible answer: "@all\n |--@web\n |  |--h1"

- **inventory-find-host**: Show a host’s groups and merged vars
  - Minimal args:
    ```json
    { "project_root": "/abs/project", "host": "h1" }
    ```
  - Example question: "What groups and vars does h1 have?"
  - Possible answer: `{ "groups": ["web"], "hostvars": {"ansible_user":"root"} }`

- **ansible-ping**: Ping hosts via ad-hoc
  - Minimal args:
    ```json
    { "project_root": "/abs/project", "host_pattern": "localhost" }
    ```
  - Example question: "Ping localhost."
  - Possible answer: `{ "ok": true, "rc": 0 }`

- **ansible-gather-facts**: Run setup and return facts
  - Minimal args:
    ```json
    { "project_root": "/abs/project", "host_pattern": "localhost" }
    ```
  - Example question: "Gather facts from localhost."
  - Possible answer: `{ "facts": {"localhost": {"ansible_hostname":"node"}} }`

- **validate-yaml**: Validate YAML files
  - Minimal args:
    ```json
    { "paths": ["/abs/file.yml"] }
    ```
  - Example question: "Validate this YAML file."
  - Possible answer: `{ "ok": true, "results": [{"path":"/abs/file.yml","ok":true}] }`

- **galaxy-install**: Install roles/collections from requirements
  - Minimal args:
    ```json
    { "project_root": "/abs/project" }
    ```
  - Example question: "Install galaxy dependencies for my project."
  - Possible answer: `{ "ok": true, "executed": [{"kind":"collection","rc":0}] }`

- **project-bootstrap**: Bootstrap project (env info + galaxy install)
  - Minimal args:
    ```json
    { "project_root": "/abs/project" }
    ```
  - Example question: "Bootstrap my project."
  - Possible answer: `{ "ok": true, "details": {"ansible_version":"..."} }`

- **inventory-diff**: Diff two inventories
  - Minimal args:
    ```json
    { "left_project_root": "/abs/project", "right_project_root": "/abs/project" }
    ```
  - Example question: "What changed between stage and prod inventories?"
  - Possible answer: `{ "added_hosts": [], "removed_hosts": [], "group_membership_changes": {} }`

- **ansible-test-idempotence**: Run playbook twice and assert no changes second run
  - Minimal args:
    ```json
    { "playbook_path": "/abs/playbook.yml", "project_root": "/abs/project" }
    ```
  - Example question: "Is this playbook idempotent?"
  - Possible answer: `{ "ok": true, "changed_total_second": 0 }`

- **galaxy-lock**: Generate a lock file of installed roles/collections
  - Minimal args:
    ```json
    { "project_root": "/abs/project" }
    ```
  - Example question: "Create a requirements.lock.yml for my project."
  - Possible answer: `{ "ok": true, "path": "/abs/requirements.lock.yml" }`

- **vault-encrypt / vault-decrypt / vault-view / vault-rekey**: Vault operations
  - Minimal args (encrypt):
    ```json
    { "file_paths": ["/abs/group_vars/all/vault.yml"], "project_root": "/abs/project" }
    ```
  - Example question: "Encrypt group_vars/all/vault.yml with my vault password."
  - Possible answer: `{ "ok": true, "rc": 0 }`
