#!/bin/bash
###############################################################################
# Script 00 : Creation / Configuration LXC Proxmox pour Docker
#
# A executer sur l'HOTE PROXMOX (pas dans le container).
#
# Deux modes automatiques :
#   - Si le container N'EXISTE PAS  -> creation + configuration Docker
#   - Si le container EXISTE DEJA   -> reconfiguration Docker (avec backup)
#
# Resout :
#   - AppArmor "permission denied"
#   - Network unreachable (pas de DHCP)
#   - Docker sysctl errors
#   - Nesting / cgroup permissions
#   - UID/GID remapping (unprivileged -> privileged)
#
# Inclut :
#   - Generation de clefs SSH (sauvegardees sur l'hote)
#   - Configuration openssh-server dans le container
#   - Installation Docker via 01-install-docker.sh (si present dans le meme dossier)
#
# Usage : ./00-create-lxc.sh <CTID> [hostname]
# Exemple : ./00-create-lxc.sh 200 agflow-docker-test
#
# Pre-requis (creation uniquement) : un template Ubuntu dans le storage local.
#   pveam update
#   pveam download local ubuntu-24.04-standard_24.04-2_amd64.tar.zst
###############################################################################
set -euo pipefail

# ── Configuration par defaut ─────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTID="${1:-}"
# Sanitize hostname: replace underscores/dots with hyphens, lowercase, strip invalid chars
CT_NAME_RAW="${2:-agflow-docker}"
CT_NAME=$(echo "${CT_NAME_RAW}" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g' | sed 's/--*/-/g' | sed 's/^-//;s/-$//')
CORES=4
MEMORY=8192
SWAP=1024
DISK_SIZE=30
STORAGE="local-lvm"
BRIDGE="vmbr0"
SSH_KEY_DIR="/root/.ssh/lxc-keys"

if [ -z "${CTID}" ]; then
    echo "Usage: $0 <CTID> [hostname]"
    echo ""
    echo "Containers disponibles :"
    pct list
    exit 1
fi

CONF="/etc/pve/lxc/${CTID}.conf"

# ══════════════════════════════════════════════════════════════════════════════
# Detecter le mode : CREATION ou RECONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
if pct status "${CTID}" &>/dev/null; then
    MODE="reconfigure"
    echo "==========================================="
    echo "  Container ${CTID} detecte -> RECONFIGURATION"
    echo "==========================================="
else
    MODE="create"
    echo "==========================================="
    echo "  Container ${CTID} inexistant -> CREATION"
    echo "==========================================="
fi
echo ""

# ══════════════════════════════════════════════════════════════════════════════
# MODE CREATION
# ══════════════════════════════════════════════════════════════════════════════
if [ "${MODE}" = "create" ]; then

    # ── Detecter le template Ubuntu ──────────────────────────────────────────
    TEMPLATE=$(pveam list local 2>/dev/null | grep -i "ubuntu-24" | awk '{print $1}' | head -1)
    [ -z "${TEMPLATE}" ] && TEMPLATE=$(pveam list local 2>/dev/null | grep -i "ubuntu-22" | awk '{print $1}' | head -1)
    [ -z "${TEMPLATE}" ] && TEMPLATE=$(pveam list local 2>/dev/null | grep -i "ubuntu" | awk '{print $1}' | head -1)

    if [ -z "${TEMPLATE}" ]; then
        echo "ERREUR : Aucun template Ubuntu trouve."
        echo ""
        echo "Templates disponibles :"
        pveam list local
        echo ""
        echo "Pour telecharger Ubuntu 24.04 :"
        echo "  pveam update"
        echo "  pveam download local ubuntu-24.04-standard_24.04-2_amd64.tar.zst"
        exit 1
    fi

    echo "  CT ID     : ${CTID}"
    echo "  Nom       : ${CT_NAME}"
    echo "  CPU       : ${CORES} cores"
    echo "  RAM       : ${MEMORY} MB"
    echo "  Swap      : ${SWAP} MB"
    echo "  Disque    : ${DISK_SIZE}G"
    echo "  Reseau    : ${BRIDGE}"
    echo "  Template  : ${TEMPLATE}"
    echo ""

    # ── Creer le container (directement privileged) ──────────────────────────
    echo "[1/3] Creation du container LXC..."
    pct create "${CTID}" "${TEMPLATE}" \
      --hostname "${CT_NAME}" \
      --cores "${CORES}" \
      --memory "${MEMORY}" \
      --swap "${SWAP}" \
      --rootfs "${STORAGE}:${DISK_SIZE}" \
      --net0 "name=eth0,bridge=${BRIDGE},firewall=1,ip=dhcp,type=veth" \
      --nameserver "8.8.8.8" \
      --searchdomain "1.1.1.1" \
      --ostype ubuntu \
      --unprivileged 0 \
      --features "nesting=1,keyctl=1" \
      --tags "agflow,docker" \
      --description "agflow.docker platform"
    echo "  -> Container cree"

    # ── Ajouter la config Docker ─────────────────────────────────────────────
    echo "[2/3] Ajout de la configuration Docker-ready..."
    cat >> "${CONF}" << 'EOF'

# Docker dans LXC — permissions necessaires
lxc.apparmor.profile: unconfined
lxc.cap.drop:
lxc.mount.auto: proc:rw sys:rw cgroup:rw
lxc.cgroup2.devices.allow: a
lxc.mount.entry: /sys/kernel/security sys/kernel/security none bind,optional 0 0
EOF
    echo "  -> Configuration Docker ajoutee"

    STEP_BOOT=3
    STEP_TOTAL=3

# ══════════════════════════════════════════════════════════════════════════════
# MODE RECONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
else

    # ── Detecter si conversion unprivileged -> privileged ────────────────────
    WAS_UNPRIVILEGED=0
    if grep -q "^unprivileged: 1" "${CONF}" 2>/dev/null; then
        WAS_UNPRIVILEGED=1
        echo "  [!] Container actuellement unprivileged -> sera converti en privileged"
        echo "      Les UIDs/GIDs du filesystem seront corriges automatiquement."
        echo ""
    fi

    # ── Arreter le container ─────────────────────────────────────────────────
    echo "[1/6] Arret du container ${CTID}..."
    pct stop "${CTID}" 2>/dev/null || true
    sleep 3
    echo "  -> Arrete"

    # ── Backup ───────────────────────────────────────────────────────────────
    echo "[2/6] Backup de la configuration..."
    cp "${CONF}" "${CONF}.backup.$(date +%Y%m%d%H%M%S)"
    echo "  -> Backup : ${CONF}.backup.*"

    # ── Lire les parametres existants ────────────────────────────────────────
    echo "[3/6] Lecture des parametres existants..."
    ARCH=$(grep "^arch:" "${CONF}" | head -1 || echo "arch: amd64")
    CORES_CONF=$(grep "^cores:" "${CONF}" | head -1 || echo "cores: 4")
    HOSTNAME_CONF=$(grep "^hostname:" "${CONF}" | head -1 || echo "hostname: docker-lxc")
    MEMORY_CONF=$(grep "^memory:" "${CONF}" | head -1 || echo "memory: 8192")
    NAMESERVER=$(grep "^nameserver:" "${CONF}" | head -1 || echo "nameserver: 8.8.8.8")
    NET0=$(grep "^net0:" "${CONF}" | head -1 || echo "")
    OSTYPE=$(grep "^ostype:" "${CONF}" | head -1 || echo "ostype: ubuntu")
    ROOTFS=$(grep "^rootfs:" "${CONF}" | head -1 || echo "")
    SEARCHDOMAIN=$(grep "^searchdomain:" "${CONF}" | head -1 || echo "searchdomain: 1.1.1.1")
    SWAP_CONF=$(grep "^swap:" "${CONF}" | head -1 || echo "swap: 1024")
    echo "  -> ${HOSTNAME_CONF}"
    echo "  -> ${CORES_CONF}, ${MEMORY_CONF}"

    # ── Remapping UIDs si necessaire ─────────────────────────────────────────
    if [ "${WAS_UNPRIVILEGED}" -eq 1 ]; then
        echo "[4/6] Correction des UIDs/GIDs (unprivileged -> privileged)..."

        pct mount "${CTID}" 2>&1 || true
        MOUNTPOINT="/var/lib/lxc/${CTID}/rootfs"

        if [ ! -d "${MOUNTPOINT}" ]; then
            echo "  -> ERREUR : impossible de trouver le rootfs monte sur ${MOUNTPOINT}"
            echo "     Verifiez manuellement : pct mount ${CTID}"
            exit 1
        fi

        echo "  -> Rootfs monte sur : ${MOUNTPOINT}"

        COUNT_UID=$(find "${MOUNTPOINT}" -uid 100000 2>/dev/null | head -100 | wc -l)
        echo "  -> Fichiers avec UID 100000 detectes : ${COUNT_UID}+"

        if [ "${COUNT_UID}" -gt 0 ]; then
            echo "  -> Remapping UIDs 100000-165535 vers 0-65535..."
            cd "${MOUNTPOINT}"
            find . -wholename ./proc -prune -o -wholename ./sys -prune -o -print0 2>/dev/null | \
            while IFS= read -r -d '' file; do
                FUID=$(stat -c '%u' "$file" 2>/dev/null) || continue
                FGID=$(stat -c '%g' "$file" 2>/dev/null) || continue
                NEW_UID="${FUID}"
                NEW_GID="${FGID}"
                if [ "${FUID}" -ge 100000 ] && [ "${FUID}" -le 165535 ]; then
                    NEW_UID=$((FUID - 100000))
                fi
                if [ "${FGID}" -ge 100000 ] && [ "${FGID}" -le 165535 ]; then
                    NEW_GID=$((FGID - 100000))
                fi
                if [ "${NEW_UID}" != "${FUID}" ] || [ "${NEW_GID}" != "${FGID}" ]; then
                    chown -h "${NEW_UID}:${NEW_GID}" "$file" 2>/dev/null || true
                fi
            done
            cd /
            echo "  -> Remapping termine"
        else
            echo "  -> Pas de remapping necessaire (UIDs deja corrects)"
        fi

        pct unmount "${CTID}"
        echo "  -> Rootfs demonte"
    else
        echo "[4/6] Deja privileged, skip remapping UIDs."
    fi

    # ── Ecrire la configuration Docker-ready ─────────────────────────────────
    echo "[5/6] Ecriture de la configuration Docker-ready..."
    cat > "${CONF}" << EOF
${ARCH}
${CORES_CONF}
features: nesting=1,keyctl=1
${HOSTNAME_CONF}
${MEMORY_CONF}
${NAMESERVER}
${NET0}
${OSTYPE}
${ROOTFS}
${SEARCHDOMAIN}
${SWAP_CONF}
unprivileged: 0

# Docker dans LXC — permissions necessaires
lxc.apparmor.profile: unconfined
lxc.cap.drop:
lxc.mount.auto: proc:rw sys:rw cgroup:rw
lxc.cgroup2.devices.allow: a
lxc.mount.entry: /sys/kernel/security sys/kernel/security none bind,optional 0 0
EOF
    echo "  -> Configuration ecrite"

    STEP_BOOT=6
    STEP_TOTAL=6
fi

# ══════════════════════════════════════════════════════════════════════════════
# COMMUN : Demarrage + Reseau + SSH + Docker
# ══════════════════════════════════════════════════════════════════════════════

# ── Demarrage ────────────────────────────────────────────────────────────────
echo "[${STEP_BOOT}/${STEP_TOTAL}] Demarrage du container..."
pct start "${CTID}"
sleep 5

if pct status "${CTID}" | grep -q running; then
    echo "  -> Container demarre"
else
    echo "  -> ERREUR : Container ne demarre pas. Verifiez les logs :"
    echo "     journalctl -xe | grep ${CTID}"
    exit 1
fi

# ── Configuration reseau DHCP ────────────────────────────────────────────────
echo ""
echo "  Configuration reseau DHCP..."
pct exec "${CTID}" -- bash -c '
if [ ! -f /etc/systemd/network/20-eth0.network ]; then
    cat > /etc/systemd/network/20-eth0.network << NETEOF
[Match]
Name=eth0

[Network]
DHCP=yes

[DHCP]
UseDNS=yes
UseRoutes=yes
NETEOF
    systemctl restart systemd-networkd
    echo "  -> Config DHCP creee"
else
    echo "  -> Config DHCP deja presente"
fi

sleep 5
IP=$(ip -4 addr show eth0 2>/dev/null | grep inet | awk "{print \$2}" | head -1)
if [ -n "$IP" ]; then
    echo "  -> IP obtenue : $IP"
else
    echo "  -> ATTENTION : pas d IP obtenue. Verifiez le DHCP."
fi

if ping -c 1 8.8.8.8 &>/dev/null; then
    echo "  -> Internet : OK"
else
    echo "  -> ATTENTION : pas de connectivite internet"
fi
'

# ── Configuration SSH ────────────────────────────────────────────────────────
echo ""
echo "  Configuration SSH..."

mkdir -p "${SSH_KEY_DIR}"

KEY_FILE="${SSH_KEY_DIR}/id_ed25519_lxc${CTID}"
if [ -f "${KEY_FILE}" ]; then
    echo "  -> Clef SSH existante : ${KEY_FILE}"
else
    echo "  -> Generation clef SSH..."
    ssh-keygen -t ed25519 -f "${KEY_FILE}" -N "" -C "proxmox-host->lxc-${CTID}" -q
    echo "  -> Clef generee : ${KEY_FILE}"
fi

PUB_KEY=$(cat "${KEY_FILE}.pub")

pct exec "${CTID}" -- bash -c "
if ! command -v sshd &>/dev/null; then
    echo '  -> Installation openssh-server...'
    apt-get update -qq >/dev/null 2>&1
    apt-get install -y -qq openssh-server >/dev/null 2>&1
    echo '  -> openssh-server installe'
else
    echo '  -> openssh-server deja present'
fi

sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#*PubkeyAuthentication.*/PubkeyAuthentication yes/' /etc/ssh/sshd_config

mkdir -p /root/.ssh
chmod 700 /root/.ssh

if ! grep -qF '${PUB_KEY}' /root/.ssh/authorized_keys 2>/dev/null; then
    echo '${PUB_KEY}' >> /root/.ssh/authorized_keys
    echo '  -> Clef publique injectee'
else
    echo '  -> Clef publique deja presente'
fi
chmod 600 /root/.ssh/authorized_keys

systemctl enable ssh >/dev/null 2>&1 || systemctl enable sshd >/dev/null 2>&1
systemctl restart ssh 2>/dev/null || systemctl restart sshd 2>/dev/null
echo '  -> sshd demarre'
"

# ── Installation Docker via 01-install-docker.sh ─────────────────────────────
DOCKER_SCRIPT="${SCRIPT_DIR}/01-install-docker.sh"
if [ -f "${DOCKER_SCRIPT}" ]; then
    echo ""
    echo "  Installation Docker via 01-install-docker.sh..."
    pct push "${CTID}" "${DOCKER_SCRIPT}" /root/01-install-docker.sh
    pct exec "${CTID}" -- chmod +x /root/01-install-docker.sh
    pct exec "${CTID}" -- /root/01-install-docker.sh
else
    echo ""
    echo "  [!] ${DOCKER_SCRIPT} introuvable -- installation Docker ignoree."
fi

# ── Creer un utilisateur agflow avec SSH ed25519 ────────────────────────────
echo ""
echo "  Creation de l'utilisateur agflow..."

AGFLOW_PASS=$(tr -dc 'A-Za-z0-9_!@#$%^&*' </dev/urandom 2>/dev/null | head -c 24 || echo "agflow$(date +%s)")

# Generer une clef ed25519 dediee pour l'utilisateur agflow
AGFLOW_KEY_FILE="${SSH_KEY_DIR}/id_ed25519_agflow_lxc${CTID}"
if [ ! -f "${AGFLOW_KEY_FILE}" ]; then
    ssh-keygen -t ed25519 -f "${AGFLOW_KEY_FILE}" -N "" -C "agflow@lxc-${CTID}" -q
    echo "  -> Clef agflow generee : ${AGFLOW_KEY_FILE}"
else
    echo "  -> Clef agflow existante : ${AGFLOW_KEY_FILE}"
fi
AGFLOW_PUB_KEY=$(cat "${AGFLOW_KEY_FILE}.pub")

pct exec "${CTID}" -- bash -c "
# Creer l'utilisateur s'il n'existe pas
if ! id agflow &>/dev/null; then
    useradd -m -s /bin/bash -G sudo,docker agflow 2>/dev/null || useradd -m -s /bin/bash agflow
    echo '  -> Utilisateur agflow cree'
else
    echo '  -> Utilisateur agflow existe deja'
fi

# Mot de passe
echo 'agflow:${AGFLOW_PASS}' | chpasswd
echo '  -> Mot de passe agflow configure'

# SSH pour agflow
mkdir -p /home/agflow/.ssh
chmod 700 /home/agflow/.ssh

if ! grep -qF '${AGFLOW_PUB_KEY}' /home/agflow/.ssh/authorized_keys 2>/dev/null; then
    echo '${AGFLOW_PUB_KEY}' >> /home/agflow/.ssh/authorized_keys
    echo '  -> Clef publique agflow injectee'
else
    echo '  -> Clef publique agflow deja presente'
fi
chmod 600 /home/agflow/.ssh/authorized_keys
chown -R agflow:agflow /home/agflow/.ssh
"

# ── Injecter la clef Wetty (terminal web) ───────────────────────────────────
echo ""
echo "  Injection clef Wetty (terminal web)..."

# Clef publique du service Wetty (agflow LXC 201) — fixe, générée une fois
WETTY_PUB="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHNerDXuUIaAU/m7AUJJaqDDKA8YJzqBRvppg85M7PpZ agflow-wetty"

pct exec "${CTID}" -- bash -c "
if ! grep -qF '${WETTY_PUB}' /home/agflow/.ssh/authorized_keys 2>/dev/null; then
    echo '${WETTY_PUB}' >> /home/agflow/.ssh/authorized_keys
    chown agflow:agflow /home/agflow/.ssh/authorized_keys
    echo '  -> Clef Wetty injectee'
else
    echo '  -> Clef Wetty deja presente'
fi

# Sudo sans mot de passe pour agflow
echo 'agflow ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/agflow
chmod 440 /etc/sudoers.d/agflow
echo '  -> sudo NOPASSWD configure'
"

# ── Recuperer les infos systeme ──────────────────────────────────────────────
CT_IP=$(pct exec "${CTID}" -- bash -c "ip -4 addr show eth0 2>/dev/null | grep inet | awk '{print \$2}' | cut -d/ -f1 | head -1" 2>/dev/null || echo "")

# Type d'adresse IP (DHCP ou static)
IP_TYPE=$(pct exec "${CTID}" -- bash -c "
if [ -f /etc/systemd/network/20-eth0.network ] && grep -q 'DHCP=yes' /etc/systemd/network/20-eth0.network 2>/dev/null; then
    echo 'dhcp'
elif grep -q 'dhcp' /etc/netplan/*.yaml 2>/dev/null; then
    echo 'dhcp'
elif grep -q 'inet dhcp' /etc/network/interfaces 2>/dev/null; then
    echo 'dhcp'
else
    echo 'static'
fi
" 2>/dev/null || echo "unknown")

# Distribution Linux
CT_DISTRO=$(pct exec "${CTID}" -- bash -c "
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo \"\${NAME} \${VERSION_ID}\"
else
    echo 'unknown'
fi
" 2>/dev/null || echo "unknown")

# ── Resume final ─────────────────────────────────────────────────────────────
echo ""
echo "==========================================="
echo "  Container ${CTID} PRET"
echo "==========================================="
echo ""
echo "  Mode        : ${MODE}"
echo ""
echo "  Systeme :"
echo "  - Distribution : ${CT_DISTRO}"
echo "  - IP           : ${CT_IP} (${IP_TYPE})"
echo ""
echo "  Infrastructure :"
echo "  - unprivileged: 0 (privileged)"
echo "  - nesting + keyctl actives"
echo "  - AppArmor: unconfined"
echo "  - cgroup2: all devices allowed"
echo ""
echo "  SSH :"
echo "  - Clef privee : ${KEY_FILE}"
echo "  - Clef publique : ${KEY_FILE}.pub"
echo "  - Root login par clef uniquement"
echo ""
echo "  Acces :"
echo "    pct enter ${CTID}"
if [ -n "${CT_IP}" ]; then
echo "    ssh -i ${KEY_FILE} root@${CT_IP}"
echo ""
echo "  IP : ${CT_IP}"
fi
echo ""
echo "  Utilisateur agflow :"
echo "  - User     : agflow"
echo "  - Password : ${AGFLOW_PASS}"
echo "  - Clef SSH : ${AGFLOW_KEY_FILE}"
echo "  - sudo     : NOPASSWD"
if [ -n "${CT_IP}" ]; then
echo "    ssh -i ${AGFLOW_KEY_FILE} agflow@${CT_IP}"
fi
echo ""
echo "  Docker :"
docker_version=$(pct exec "${CTID}" -- docker --version 2>/dev/null || echo "non installe")
compose_version=$(pct exec "${CTID}" -- docker compose version 2>/dev/null || echo "non installe")
echo "    ${docker_version}"
echo "    ${compose_version}"
echo ""
echo "==========================================="
echo ""
# ── Sortie JSON (convention pipeline agflow) ─────────────────────────────────
echo "{\"status\":\"ok\",\"ctid\":\"${CTID}\",\"ip\":\"${CT_IP}\",\"ip_type\":\"${IP_TYPE}\",\"distro\":\"${CT_DISTRO}\",\"user\":\"agflow\",\"password\":\"${AGFLOW_PASS}\",\"ssh_key\":\"${AGFLOW_KEY_FILE}\",\"docker\":\"${docker_version}\"}"
