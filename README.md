MCP Ansible Server

Advanced Ansible Model Context Protocol (MCP) server in Python exposing Ansible utilities for inventories, playbooks, roles, and project workflows.

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

Notes

- The server uses stdio transport. Do not print to stdout; logs go to stderr.
- Ansible connection/auth follows your local Ansible configuration.

Reference

- MCP Quickstart (Python): https://modelcontextprotocol.io/quickstart/server#python

