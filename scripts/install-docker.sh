#!/bin/bash
###############################################################################
# Script 01 : Installation de Docker dans un Container LXC
#
# A executer DANS le container LXC (en tant que root).
# Adapte pour LXC privileged (pas de sudo, pas de qemu-guest-agent).
#
# Usage depuis l'hote Proxmox :
#   pct exec <CTID> -- bash -c "$(wget -qLO - <URL>)"
#
# Ou depuis l'interieur du container :
#   bash -c "$(wget -qLO - <URL>)"
###############################################################################
set -euo pipefail

# ── Mode non-interactif pour apt/dpkg ─────────────────────────────────────────
# Evite tout prompt (conffile modifie, debconf, etc.) qui bloquerait le script
# quand il est lance via pct exec. --force-confold garde la version locale des
# fichiers de config deja modifies (ex: sshd_config touche par le script 00).
export DEBIAN_FRONTEND=noninteractive
APT_OPTS=(-o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef)

echo "==========================================="
echo "  Installation Docker (LXC)"
echo "==========================================="
echo ""

# ── Verifier qu'on est root ──────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo "ERREUR : Ce script doit etre execute en tant que root."
    echo "         Pas de sudo dans un LXC — connectez-vous en root."
    exit 1
fi

# ── 1. Mise a jour systeme ───────────────────────────────────────────────────
echo "[1/6] Mise a jour du systeme..."
apt-get update -qq
apt-get "${APT_OPTS[@]}" upgrade -y -qq
echo "  -> OK"

# ── 2. Outils de base ───────────────────────────────────────────────────────
echo "[2/6] Installation des outils de base..."
apt-get "${APT_OPTS[@]}" install -y -qq \
  curl wget git vim htop tmux \
  ca-certificates gnupg lsb-release \
  python3 python3-pip python3-venv \
  openssh-server
echo "  -> OK"

# ── 3. Ajout du repo Docker ─────────────────────────────────────────────────
echo "[3/6] Ajout du depot Docker officiel..."
install -m 0755 -d /etc/apt/keyrings

if [ ! -f /etc/apt/keyrings/docker.gpg ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
      gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
fi

echo "deb [arch=$(dpkg --print-architecture) \
  signed-by=/etc/apt/keyrings/docker.gpg] \
  https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

echo "  -> OK"

# ── 4. Installation Docker ──────────────────────────────────────────────────
echo "[4/6] Installation de Docker Engine..."
apt-get update -qq
apt-get "${APT_OPTS[@]}" install -y -qq \
  docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
echo "  -> OK"

# ── 5. Configuration Docker production ──────────────────────────────────────
echo "[5/6] Configuration Docker pour la production..."
mkdir -p /etc/docker

tee /etc/docker/daemon.json > /dev/null << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  },
  "default-address-pools": [
    {"base": "172.20.0.0/16", "size": 24}
  ],
  "storage-driver": "overlay2",
  "live-restore": true
}
EOF

systemctl enable docker
systemctl restart docker

# Ajouter l'utilisateur agflow au groupe docker (s'il existe)
if id agflow &>/dev/null; then
    usermod -aG docker agflow
    echo "  -> agflow ajouté au groupe docker"
fi
echo "  -> OK"

# ── 6. Caddy reverse proxy (TLS interne) ─────────────────────────────────────
echo "[6/6] Installation de Caddy (reverse proxy)..."
apt-get "${APT_OPTS[@]}" install -y -qq debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg 2>/dev/null
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list > /dev/null
apt-get update -qq
apt-get "${APT_OPTS[@]}" install -y -qq caddy

# Generate Caddyfile — reverse proxy minimal (HTTP)
# Le SSL est gere par Cloudflare Tunnel en front — pas besoin de TLS ici.
# Les domaines agflow.docker sont a ajouter manuellement apres deploiement.
cat > /etc/caddy/Caddyfile << 'CADDYEOF'
# ── agflow.docker — Reverse Proxy ──────────────────
# Caddy ecoute en HTTP sur le port 80.
# Cloudflare Tunnel gere le SSL cote navigateur.
#
# Pour ajouter un domaine : dupliquer le bloc exemple ci-dessous,
# decommenter, adapter, puis : systemctl reload caddy

:80 {
    # Exemple : decommenter et adapter pour chaque service expose
    #
    # @admin host admin.example.org
    # handle @admin {
    #     reverse_proxy localhost:8080
    # }

    handle {
        respond "agflow.docker — no route configured" 404
    }
}
CADDYEOF

systemctl enable caddy
systemctl restart caddy
echo "  -> Caddy installe et configure"

# ── Verification ─────────────────────────────────────────────────────────────
echo ""
echo "  Verification..."
echo ""

if docker info &>/dev/null; then
    echo "  Docker Engine : $(docker --version)"
    echo "  Compose       : $(docker compose version)"
    echo ""

    # Test rapide
    if docker run --rm hello-world &>/dev/null; then
        echo "  Docker run    : OK"
    else
        echo "  Docker run    : echec (premier lancement peut etre lent)"
    fi
else
    echo "  ERREUR : Docker ne repond pas."
    echo "  Verifiez : systemctl status docker"
    exit 1
fi

# ── 7. Deployer Alloy (collecteur logs vers Loki central) ────────────────────
echo "[7/7] Deploiement Alloy (collecteur logs)..."
LOKI_URL="${LOKI_URL:-http://192.168.10.158:3100/loki/api/v1/push}"
HOSTNAME_LABEL="${HOSTNAME_LABEL:-$(hostname)}"
RAW_BASE="https://raw.githubusercontent.com/gaelgael5/agflow.docker/refs/heads/feat/mom-bus/infra/alloy-agent"

mkdir -p /root/alloy-agent
wget -qO /root/alloy-agent/docker-compose.yml "${RAW_BASE}/docker-compose.yml"
wget -qO /root/alloy-agent/config.alloy "${RAW_BASE}/config.alloy"

cat > /root/alloy-agent/.env << EOF
LOKI_URL=${LOKI_URL}
HOSTNAME=${HOSTNAME_LABEL}
EOF

cd /root/alloy-agent
docker compose up -d 2>&1
echo "  -> Alloy deploye -> push vers ${LOKI_URL} (host=${HOSTNAME_LABEL})"

DOCKER_VER=$(docker --version 2>/dev/null || echo "inconnu")
COMPOSE_VER=$(docker compose version 2>/dev/null || echo "inconnu")
NODE_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "")
CADDY_VER=$(caddy version 2>/dev/null | head -1 || echo "inconnu")

echo ""
echo "==========================================="
echo "  Docker + Caddy installes dans le LXC."
echo ""
echo "  Docker  : ${DOCKER_VER}"
echo "  Compose : ${COMPOSE_VER}"
echo "  Caddy   : ${CADDY_VER}"
echo "  IP      : ${NODE_IP}"
echo ""
echo "  Caddy ecoute sur :80 (HTTP — SSL gere par Cloudflare Tunnel)."
echo "  Aucun domaine configure — editer /etc/caddy/Caddyfile puis :"
echo "    systemctl reload caddy"
echo ""
echo "  Prochaine etape :"
echo "  - Deployer la stack agflow.docker (docker compose up -d)"
echo "  - Configurer le tunnel Cloudflare (service: http://<IP>:80)"
echo "==========================================="

# ── Sortie JSON (convention pipeline agflow) ─────────────────────────────────
echo "{\"status\":\"ok\",\"docker\":\"${DOCKER_VER}\",\"compose\":\"${COMPOSE_VER}\",\"caddy\":\"${CADDY_VER}\",\"ip\":\"${NODE_IP}\"}"
