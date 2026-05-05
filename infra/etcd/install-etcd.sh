#!/usr/bin/env bash
# Installe etcd binaire (LOT 20) — à exécuter dans le LXC 210.
set -euo pipefail

ETCD_VERSION="${ETCD_VERSION:-v3.5.12}"
ETCD_USER="etcd"

apt-get update
apt-get install -y --no-install-recommends curl ca-certificates

if ! id "$ETCD_USER" >/dev/null 2>&1; then
    useradd --system --home /var/lib/etcd --shell /usr/sbin/nologin "$ETCD_USER"
fi

mkdir -p /var/lib/etcd /etc/etcd /var/log/etcd
chown -R "$ETCD_USER:$ETCD_USER" /var/lib/etcd /var/log/etcd

if ! command -v etcd >/dev/null 2>&1; then
    cd /tmp
    curl -fsSL "https://github.com/etcd-io/etcd/releases/download/${ETCD_VERSION}/etcd-${ETCD_VERSION}-linux-amd64.tar.gz" \
        -o etcd.tar.gz
    tar xzf etcd.tar.gz
    install -m 0755 "etcd-${ETCD_VERSION}-linux-amd64/etcd" /usr/local/bin/etcd
    install -m 0755 "etcd-${ETCD_VERSION}-linux-amd64/etcdctl" /usr/local/bin/etcdctl
    rm -rf "etcd-${ETCD_VERSION}-linux-amd64" etcd.tar.gz
fi

echo "etcd ${ETCD_VERSION} installed."
echo "Next : push /etc/etcd/etcd.conf.yml then enable systemd service."
