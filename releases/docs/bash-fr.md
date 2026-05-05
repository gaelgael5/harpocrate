# CLI Bash

Orchestrateur bash léger délégant toute la cryptographie au helper Python. Idéal pour les scripts CI/CD et les Dockerfiles.

## Installation

```bash
# Télécharger et extraire
curl -fsSL https://vault.yoops.org/v1/sdk/cli-bash -o harpocrate-cli.tar.gz
tar -xzf harpocrate-cli.tar.gz

# Rendre exécutable et placer dans le PATH
chmod +x harpocrate-cli
sudo mv harpocrate-cli /usr/local/bin/

# Vérifier l'installation
harpocrate-cli --help
```

## Démarrage rapide

```bash
export HARPOCRATE_TOKEN="hrpv_1_..."
export HARPOCRATE_URL="https://vault.yoops.org"

# Lister les secrets
harpocrate-cli list

# Lire un secret
harpocrate-cli get ANTHROPIC_API_KEY

# Peupler un placeholder
harpocrate-cli populate DATABASE_PASSWORD

# Peupler tous les placeholders
harpocrate-cli populate-all

# Utiliser dans un script
DB_PASS=$(harpocrate-cli get DATABASE_PASSWORD)
psql "postgresql://user:${DB_PASS}@localhost/mydb"
```

## Commande `get-or-populate`

```bash
# get-or-populate : lit la valeur, la génère si c'est un placeholder
SECRET=$(harpocrate-cli get-or-populate MY_API_KEY)
echo "Secret prêt : ${SECRET:0:4}..."
```

## Permissions requises

Mêmes permissions que pour le SDK Python (cf. doc Python). Dépend des opérations utilisées.
