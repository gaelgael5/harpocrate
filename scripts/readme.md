
# LXC — Provisioning & Deployment

Scripts to provision **Proxmox LXC containers** ready for Docker / Docker
Swarm, install a Grafana Alloy log collector, and deploy the **ag.flow**
stack on the production LXC.

> 🇫🇷 Pour la version française, voir [readme-lxc-fr.md](readme-lxc-fr.md).
> 🖥️ Pour la version VM (Proxmox QEMU), voir [readme-vm.md](readme-vm.md).

> **All scripts are published** in this repo
> (`https://github.com/Configurations/Proxmox`, `main` branch). The
> commands below download them on the fly from GitHub raw — no need to
> clone.

```bash
BASE="https://raw.githubusercontent.com/gaelgael5/harpocrate/refs/heads/main/scripts"
```

Three execution targets — each script states in its header where it
should run:

| Target | Scripts |
|---|---|
| Proxmox host (root) | `create-lxc.sh` |
| Inside the LXC (root) | `03-install-alloy.sh` |

---

## `create-lxc.sh` *(Proxmox host)* — main entry point

A single self-contained script that **creates or reconfigures** a
Docker-ready privileged LXC and, depending on the flags, installs
Docker, prepares Swarm, initializes a cluster or joins one. Replaces
the previous `00-create-lxc.sh` + `00-create-lxc-swarm.sh` +
`01-install-docker.sh` + `02-init-swarm.sh` + `02-join-swarm.sh`.

### Modes & flags

| Flag | Effect |
|---|---|
| *(none)* | Bare LXC — no Docker, no Swarm permissions in the LXC config |
| `--docker` | Installs Docker + LXC permissions (apparmor unconfined, cgroup2, mount, /sys/kernel/security) |
| `--swarm` | Prepares the LXC swarm-ready (host kernel modules, `/dev/net/tun`, sysctls, `swarm-ready` tag) |
| `--init-swarm` | Initializes a new Swarm cluster (implies `--docker` + `--swarm`) |
| `--join-swarm --manager-ip <IP> --token <TOKEN> [--as-manager]` | Joins an existing cluster (implies `--docker` + `--swarm`) |

`--init-swarm` and `--join-swarm` are mutually exclusive.

### Auto behaviors

- **Mode auto-detection** — container missing → creation; container
  exists → reconfiguration (config backup, conversion `unprivileged → privileged`
  with UID/GID remapping `100000-165535 → 0-65535` if needed).
- **Storage selection** (`STORAGE=auto` by default) — dashboard of all
  storages supporting rootfs, picks the one with the most free space,
  checks available space **before** `pct create`, refuses if
  insufficient (suggests an alternative). Adjustable safety margin via
  `SAFETY_MARGIN_GB=5`.
- **Ubuntu template auto-detection** — `ubuntu-24` first, fallback
  `ubuntu-22`.
- **Post-install Docker check** — fails clearly if the install died
  midway (e.g. saturated pool).
- **Live-restore auto-fix** — `--init-swarm` detects and corrects
  `live-restore=true` (incompatible with Swarm) when `AUTO_FIX=1`
  (default).
- **JSON output** — single aggregated final block:
  `{"status", "exit_code", "machine":{...}, "docker":{...}, "swarm":{...}}`.
  `docker` block present only with `--docker`, `swarm` block only with
  `--init-swarm`/`--join-swarm`.

### Generated artifacts

- ed25519 SSH key pair stored on the host:
  `/root/.ssh/lxc-keys/id_ed25519_lxc<CTID>` (root) +
  `/root/.ssh/lxc-keys/id_ed25519_agflow_lxc<CTID>` (`agflow`).
- `agflow` user (sudo NOPASSWD, random 24-char password, member of
  `docker` group when `--docker` is on).
- For `--init-swarm`: tokens persisted to
  `/root/.ssh/lxc-keys/swarm-tokens-<CTID>.json` (chmod 600).

### Variables (defaults)

| Var | Default | Role |
|---|---|---|
| `CORES` | `4` | CPU cores |
| `MEMORY` | `8192` | RAM (MB) |
| `SWAP` | `1024` | swap (MB) |
| `DISK_SIZE` | `30` | rootfs (GB) |
| `STORAGE` | `auto` | rootfs pool (or named pool) |
| `BRIDGE` | `vmbr0` | network bridge |
| `SAFETY_MARGIN_GB` | `5` | min free margin in pool |
| `SSH_KEY_DIR` | `/root/.ssh/lxc-keys` | SSH keys folder |
| `LIVE_RESTORE` | `0` | Docker live-restore (0=false, Swarm-compatible) |
| `DOCKER_ADDR_POOL` | `172.30.0.0/16` | Docker bridges IP pool |
| `POOL_OVERLAY` | `10.20.0.0/16` | Swarm overlay pool (init-swarm) |
| `POOL_MASK` | `24` | overlay subnets size |
| `NODE_LABELS` | `role=control,tenant=agflow` | Swarm node labels |
| `FORCE` | `0` | reset Swarm before re-init (**destructive**) |
| `FORCE_LEAVE` | `no` | leave current Swarm before joining |
| `AUTO_FIX` | `1` | auto-fix live-restore=true |

### Prerequisites (creation)

An Ubuntu template available locally:

```bash
pveam update && pveam download local ubuntu-24.04-standard_24.04-2_amd64.tar.zst
```

### Examples

```bash
BASE="https://raw.githubusercontent.com/Configurations/Proxmox/main/LXC"

# 1) Bare LXC (just provisioned, no Docker)
mkdir -p /root/lxc && cd /root/lxc && \
  curl -fsSL -o create-lxc.sh "$BASE/create-lxc.sh" && chmod +x create-lxc.sh && \
  ./create-lxc.sh 200 ag-base

# 2) LXC + Docker
./create-lxc.sh 201 ag-docker --docker

# 3) Swarm manager (init a new cluster)
./create-lxc.sh 300 ag-swarm-mgr --init-swarm

# 4) Worker joining an existing cluster
./create-lxc.sh 301 ag-worker-1 \
    --join-swarm \
    --manager-ip 192.168.10.115 \
    --token SWMTKN-1-xxxxxxxxx

# 5) Additional manager (HA)
./create-lxc.sh 302 ag-mgr-2 \
    --join-swarm \
    --manager-ip 192.168.10.115 \
    --token SWMTKN-1-yyyyyyyyy \
    --as-manager

# 6) Tuning resources + storage
STORAGE=extended-lvm DISK_SIZE=80 CORES=8 MEMORY=16384 \
    ./create-lxc.sh 400 ag-data --init-swarm
```

---

## `create-lxc.json` — UI manifest

Manifest describing arguments collected by the orchestration UI before
running the script. Conforms to `script-manifest.schema.json`.

Fields: `LXC_ID` (integer), `LXC_NAME` (string), `MODE` (select:
`bare`/`docker`/`swarm`/`init-swarm`/`join-swarm`), `STORAGE`,
`DISK_SIZE`, `CORES`, `MEMORY`, `SWAP`, `BRIDGE`, `MANAGER_IP`,
`JOIN_TOKEN`, `JOIN_AS_MANAGER`, `POOL_OVERLAY`, `NODE_LABELS`.

The `command` field rewrites `MODE` to flags via a `case`, adds
`--as-manager` if requested, then runs `create-lxc.sh` with all the
named env vars.

---

## Auxiliary scripts (LXC-side, unchanged)

### `03-install-alloy.sh` *(inside the LXC, root)*

Installs **Grafana Alloy** as a log collector (Docker + journald)
pushing to Loki. Auto-detection:

- Docker present → `docker-compose.yml` (`grafana/alloy`, expected
  files in `/tmp/alloy-agent/`)
- Docker absent → Debian package + systemd service, config in
  `/etc/alloy/config.alloy`

**Required env**: `LOKI_URL`, `HOSTNAME` (LXC `host` label).

```bash
LOKI_URL="http://192.168.10.116:3100/loki/api/v1/push" HOSTNAME="lxc201" \
    bash -c "$(curl -fsSL "$BASE/03-install-alloy.sh")"
```

### `deploy-alloy-all.sh` *(local workstation)*

Deploys Alloy on **all** active homelab LXCs via the Proxmox host
(SSH alias `pve`) used as a bastion. Assumes the **ag.flow** repo
checkout (paths `../..`).

| Var | Default |
|---|---|
| `PVE_HOST` | `pve` |
| `LOKI_URL` | *(required)* |
| `LXC_HOSTS` | `101 102 108 111 112 113 114 115 116 117 201` |

### `Caddyfile.prod`, `.env.prod.example`, `.env.deploy`

Production Caddy config + env templates for the **ag.flow** stack on
LXC 203. `Caddyfile.prod` listens on `:80` (TLS upstream via
Cloudflare Tunnel), reverse-proxies `/api/*` to backend `:8000` and
serves the SPA from `/opt/agflow/frontend/dist`. `.env.deploy` should
be **gitignored** (contains `KEYCLOAK_CLIENT_SECRET`).

---

## Pipeline (use cases)

### Case A — Single-node Docker LXC (ag.flow prod stack)

```bash
# 1) Provision LXC + Docker
mkdir -p /root/lxc && cd /root/lxc && \
  curl -fsSL -o create-lxc.sh "$BASE/create-lxc.sh" && chmod +x create-lxc.sh && \
  ./create-lxc.sh 203 agflow-prod --docker

# 2) (optional) Alloy collector inside the LXC
LOKI_URL="http://192.168.10.116:3100/loki/api/v1/push" HOSTNAME="lxc203" \
    bash -c "$(curl -fsSL "$BASE/03-install-alloy.sh")"

# 3) From the workstation, in the cloned ag.flow repo
./infra/deploy.sh
```

### Case B — Docker Swarm cluster

```bash
# 1) First manager
./create-lxc.sh 300 ag-swarm-mgr --init-swarm

# Tokens are persisted to /root/.ssh/lxc-keys/swarm-tokens-300.json
WORKER_TOKEN=$(jq -r .worker_token /root/.ssh/lxc-keys/swarm-tokens-300.json)
MANAGER_IP=$(jq -r .manager_ip /root/.ssh/lxc-keys/swarm-tokens-300.json)

# 2) Worker
./create-lxc.sh 301 ag-worker-1 \
    --join-swarm --manager-ip "$MANAGER_IP" --token "$WORKER_TOKEN"

# 3) Additional manager (HA)
MANAGER_TOKEN=$(jq -r .manager_token /root/.ssh/lxc-keys/swarm-tokens-300.json)
./create-lxc.sh 302 ag-mgr-2 \
    --join-swarm --manager-ip "$MANAGER_IP" --token "$MANAGER_TOKEN" --as-manager
```

---

## ⚠️ Limitations — IPVS in privileged LXC

Docker Swarm's routing mesh and service VIPs use **IPVS** in a hidden
network namespace. In a privileged LXC, IPVS rules are correctly
installed but **forwarding does not traverse the nested namespace
correctly**. Consequence: any TCP traffic going through a Swarm VIP
times out silently. ICMP works, but TCP doesn't.

### 1. Ingress routing mesh

Default port publishing (`mode: ingress`) is broken in LXC. Service
shows `Up X minutes (healthy)` but `curl localhost:<port>` times out.

**Workaround — `mode: host` on every published port**:

```yaml
ports:
  - target: 8080
    published: 8080
    mode: host        # bypasses ingress, works in LXC
```

Trade-off: no load balancing across nodes, the port is published
on the node where the replica runs.

### 2. Service VIP (inter-service traffic)

Even on the same overlay network, `nc -zv postgres 5432` times out
when going through the service VIP. DNS resolves, ICMP works, but
TCP doesn't.

**Workaround — `endpoint_mode: dnsrr` mandatory on every service**:

```yaml
services:
  postgres:
    image: postgres:16-alpine
    deploy:
      replicas: 1
      endpoint_mode: dnsrr   # ← MANDATORY in LXC, otherwise TCP timeout
```

### Real fix

**Migrate to a Proxmox VM** — see [`readme-vm.md`](readme-vm.md) and
the `create-vm.sh` companion script. Swarm's routing mesh works
correctly in a VM (own kernel, IPVS native). Keeping the LXC is an
explicit trade-off to save homelab resources.

---

## Variables (summary)

| Var | Role |
|---|---|
| `CTID` (arg 1) | container ID |
| `CT_NAME` (arg 2) | hostname (default `agflow-docker`) |
| `--docker`, `--swarm`, `--init-swarm`, `--join-swarm` | operating mode |
| `--manager-ip`, `--token`, `--as-manager` | join-swarm params |
| `CORES`, `MEMORY`, `SWAP`, `DISK_SIZE`, `STORAGE`, `BRIDGE`, `SAFETY_MARGIN_GB`, `SSH_KEY_DIR` | resources |
| `LIVE_RESTORE`, `DOCKER_ADDR_POOL`, `DOCKER_ADDR_POOL_SIZE`, `MIN_FREE_MB` | Docker tuning |
| `POOL_OVERLAY`, `POOL_MASK`, `NODE_LABELS`, `TOKEN_DIR`, `FORCE`, `AUTO_FIX` | init-swarm |
| `ADVERTISE_ADDR`, `LISTEN_ADDR`, `FORCE_LEAVE` | join-swarm |
| `LOKI_URL`, `HOSTNAME` | `03-install-alloy.sh` |
| `PVE_HOST`, `LXC_HOSTS` | `deploy-alloy-all.sh` |
| `KEYCLOAK_CLIENT_SECRET` | `deploy.sh` (via `.env.deploy`) |