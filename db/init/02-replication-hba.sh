#!/bin/bash
# Ajoute une entrée pg_hba.conf autorisant les connexions de réplication
# (md5) depuis n'importe quel host. Sans ça, pg_basebackup d'un standby
# externe échoue avec "no pg_hba.conf entry for replication".
#
# Exécuté une seule fois, au premier init du conteneur Postgres (data dir
# vide). Si le data dir existe déjà, ce script N'EST PAS rejoué — l'admin
# doit éditer pg_hba.conf à la main ou faire un reset complet.
#
# Sécurité : en dev sur réseau interne uniquement. En prod, restreindre
# le CIDR (réseau du standby) au lieu de 0.0.0.0/0, et tunneliser via
# WireGuard ou Cloudflare Tunnel.

set -euo pipefail

echo "host replication all 0.0.0.0/0 md5" >> "${PGDATA}/pg_hba.conf"
echo "host replication all ::/0          md5" >> "${PGDATA}/pg_hba.conf"
echo "[init] pg_hba.conf : replication entries added (0.0.0.0/0 + ::/0 md5)"
