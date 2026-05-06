#!/usr/bin/env bash
# Installe Postgres 16 + Patroni dans un LXC (LOT 20).
set -euo pipefail

apt-get update
apt-get install -y --no-install-recommends \
    postgresql-16 postgresql-client-16 \
    python3-pip python3-dev libpq-dev gcc \
    ca-certificates curl

systemctl stop postgresql || true
systemctl disable postgresql || true   # Patroni gère l'instance, pas systemd

pip install --break-system-packages "patroni[etcd3]>=3.2,<4" psycopg2-binary

mkdir -p /etc/patroni/callbacks
chown -R postgres:postgres /etc/patroni

echo "Patroni installed."
echo "Next : push patroni.yml + .env + callbacks then enable systemd service."
