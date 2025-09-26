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

**Core Ansible Tools:**
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
- project-run-playbook: Run a playbook using a registered project's inventory/env

**Local inventory suite (no AAP/AWX):**
- inventory-parse: Parse inventories (ansible.cfg-aware), return hosts/groups/hostvars
- inventory-graph: Show group/host graph
- inventory-find-host: Show a host's groups and merged vars
- ansible-ping: Ad-hoc ping module
- ansible-gather-facts: Run setup and return parsed facts
- validate-yaml: Validate YAML files with error locations
- galaxy-install: Install roles/collections from requirements
- project-bootstrap: Galaxy install + env inspection

**Advanced Troubleshooting Suite:**

*Foundation Tools:*
- ansible-remote-command: Execute arbitrary shell commands with enhanced output parsing
- ansible-fetch-logs: Fetch and analyze log files with pattern detection and correlation
- ansible-service-manager: Manage services with status checking and log correlation

*Intelligent Diagnostics:*
- ansible-diagnose-host: Comprehensive health assessment with scoring and recommendations
- ansible-capture-baseline: Capture system state snapshots for comparison
- ansible-compare-states: Time-travel debugging with baseline comparisons

*Automation & Self-Healing:*
- ansible-auto-heal: Intelligent automated problem resolution with safety checks

*Network & Security:*
- ansible-network-matrix: Comprehensive network connectivity testing between hosts
- ansible-security-audit: Security vulnerability assessment and compliance checking

*Performance & Monitoring:*
- ansible-health-monitor: Continuous monitoring with trend analysis and anomaly detection
- ansible-performance-baseline: Performance benchmarking and regression detection
- ansible-log-hunter: Advanced log correlation and pattern hunting across multiple sources

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

## Troubleshooting Suite Reference

### Foundation Tools

- **ansible-remote-command**: Execute shell commands with enhanced parsing
  - Minimal args:
    ```json
    { "host_pattern": "webserver", "command": "ps aux | grep nginx" }
    ```
  - Example question: "Show me all nginx processes on the webserver."
  - Sample answer: `{ "ok": true, "stdout": "Process list...", "parsed_output": {...} }`

- **ansible-fetch-logs**: Fetch and analyze log files
  - Minimal args:
    ```json
    { "host_pattern": "app*", "log_paths": ["/var/log/nginx/error.log"], "analyze": true }
    ```
  - Example question: "Get the last 100 lines from nginx error logs and analyze patterns."
  - Sample answer: `{ "ok": true, "logs": {...}, "summary": {"total_logs": 1, "successful": 1} }`

- **ansible-service-manager**: Service management with logs
  - Minimal args:
    ```json
    { "host_pattern": "web", "service_name": "nginx", "action": "restart", "check_logs": true }
    ```
  - Example question: "Restart nginx service and show recent logs."
  - Sample answer: `{ "ok": true, "action_result": {...}, "status": {...}, "logs": {...} }`

### Intelligent Diagnostics

- **ansible-diagnose-host**: Comprehensive health assessment
  - Minimal args:
    ```json
    { "host_pattern": "production", "checks": ["system", "network", "security"], "include_recommendations": true }
    ```
  - Example question: "Run a complete health check on production servers with recommendations."
  - Sample answer: `{ "ok": true, "diagnosis": {...}, "health_score": {"score": 85, "level": "good"} }`

- **ansible-capture-baseline**: Capture system state baseline
  - Minimal args:
    ```json
    { "host_pattern": "web*", "snapshot_name": "pre-deployment", "include": ["configs", "processes"] }
    ```
  - Example question: "Capture a baseline snapshot before deployment."
  - Sample answer: `{ "ok": true, "snapshot_id": "snapshot_20250101_120000_abc123", "categories_captured": [...] }`

- **ansible-compare-states**: Compare against baseline
  - Minimal args:
    ```json
    { "host_pattern": "web*", "baseline_snapshot_id": "snapshot_20250101_120000_abc123" }
    ```
  - Example question: "Compare current state with pre-deployment baseline."
  - Sample answer: `{ "ok": true, "comparison": {"differences": {...}, "summary": {...}} }`

### Automation & Self-Healing

- **ansible-auto-heal**: Automated problem resolution
  - Minimal args:
    ```json
    { "host_pattern": "database", "symptoms": ["high_memory", "disk_full"], "max_impact": "medium", "dry_run": true }
    ```
  - Example question: "Automatically heal memory and disk issues on database servers (preview mode)."
  - Sample answer: `{ "ok": true, "proposed_actions": [...], "summary": {"actionable_symptoms": 2} }`

### Network & Security

- **ansible-network-matrix**: Network connectivity testing
  - Minimal args:
    ```json
    { "host_patterns": ["web*", "db*"], "check_ports": [22, 3306, 443] }
    ```
  - Example question: "Test network connectivity between web and database servers."
  - Sample answer: `{ "ok": true, "network_matrix": {...}, "summary": {"source_patterns": 2, "ports_tested": [22, 3306, 443]} }`

- **ansible-security-audit**: Security vulnerability assessment
  - Minimal args:
    ```json
    { "host_pattern": "all", "audit_categories": ["packages", "permissions", "network"], "generate_report": true }
    ```
  - Example question: "Run a comprehensive security audit on all servers."
  - Sample answer: `{ "ok": true, "audit": {...}, "security_assessment": {"score": 75, "level": "warning"} }`

### Performance & Monitoring

- **ansible-health-monitor**: Continuous monitoring with trends
  - Minimal args:
    ```json
    { "host_pattern": "production", "monitoring_duration": 300, "metrics_interval": 30 }
    ```
  - Example question: "Monitor production servers for 5 minutes and analyze trends."
  - Sample answer: `{ "ok": true, "monitoring": {"trend_analysis": {...}, "anomalies": []} }`

- **ansible-performance-baseline**: Performance benchmarking
  - Minimal args:
    ```json
    { "host_pattern": "web*", "benchmark_duration": 60, "store_baseline": true }
    ```
  - Example question: "Run performance benchmarks on web servers and store as baseline."
  - Sample answer: `{ "ok": true, "baseline": {"benchmarks": {...}, "performance_assessment": {"score": 90}} }`

- **ansible-log-hunter**: Advanced log correlation
  - Minimal args:
    ```json
    { "host_pattern": "app*", "search_patterns": ["ERROR", "CRITICAL"], "time_range": "1h", "correlation_window": 300 }
    ```
  - Example question: "Hunt for errors in application logs from the last hour and correlate events."
  - Sample answer: `{ "ok": true, "hunt_results": {...}, "correlation": {"correlated_events": 3} }`

## Key Features of Troubleshooting Suite

### 🎯 **Intelligent Analysis**
- **Health Scoring**: Automated scoring based on CPU, memory, disk, network, and security metrics
- **Pattern Recognition**: Smart analysis of log patterns, error correlations, and system anomalies
- **Trend Detection**: Real-time monitoring with trend analysis and predictive insights

### 🔧 **Automated Remediation**
- **Symptom-to-Solution Mapping**: Intelligent problem resolution based on detected symptoms
- **Safety-First Approach**: Graduated response with impact assessment and mandatory safety checks
- **Dry-Run Mode**: Preview all actions before execution for safety validation

### 📊 **Advanced Analytics**
- **Baseline Comparisons**: Time-travel debugging with comprehensive state comparisons
- **Performance Benchmarking**: Establish baselines and detect performance regressions
- **Security Auditing**: Comprehensive vulnerability assessment with compliance scoring

### 🛡️ **Enterprise-Grade Safety**
- **Impact Controls**: Configurable impact levels (low/medium/high) with approval workflows
- **Audit Trails**: Complete logging of all troubleshooting actions and decisions
- **Rollback Capabilities**: Automated reversion for failed operations

### 🔄 **Pure Ansible Integration**
- **No SSH Dependencies**: All operations go through Ansible's native connection framework
- **Module Consistency**: Uses standard Ansible modules for maximum compatibility
- **Configuration Aware**: Respects ansible.cfg and existing project configurations

All troubleshooting tools maintain the same safety, auditability, and Ansible-native approach while providing enterprise-grade automation capabilities.
