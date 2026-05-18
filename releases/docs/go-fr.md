# SDK Go

Client Go zero-knowledge pour Harpocrate Vault. Compatible Go 1.21+.

Le SDK déchiffre les secrets côté client — le serveur ne voit jamais les valeurs en clair.

## Installation

Télécharger l'archive depuis cette page, extraire et ajouter au `go.mod` via `replace` :

```bash
tar -xzf harpocrate-go-sdk-0.1.0.tar.gz -C ./vendor/harpocrate
```

Puis dans `go.mod` :

```go
require github.com/gaelgael5/harpocrate-sdk-go v0.1.0

replace github.com/gaelgael5/harpocrate-sdk-go => ./vendor/harpocrate
```

## Usage

```go
package main

import (
    "context"
    "fmt"
    "log"

    "github.com/gaelgael5/harpocrate-sdk-go/harpocrate"
)

func main() {
    ctx := context.Background()
    client, err := harpocrate.NewVaultClient(ctx,
        "hrpv_1_...",                  // ton API token
        "https://vault.example.com",
    )
    if err != nil {
        log.Fatal(err)
    }

    // Crée un secret
    id, _ := client.CreateSecret(ctx, "DB_PASSWORD", "s3cret!")
    fmt.Println("id =", id)

    // Récupère et déchiffre côté client
    value, _ := client.GetSecret(ctx, "DB_PASSWORD")
    fmt.Println("value =", value)

    // Met à jour
    gen, _ := client.PutSecret(ctx, "DB_PASSWORD", "n3w-s3cret!")
    _ = gen

    // Supprime
    _ = client.DeleteSecret(ctx, "DB_PASSWORD")
}
```

## Secrets organisés en arborescence (path-style)

```go
client.CreateSecret(ctx, "/db/prod/password", "s3cret!")
value, _ := client.GetSecret(ctx, "/db/prod/password")
```

Le SDK utilise la résolution `/by-id/<uuid>` pour les secrets path-style :
détection automatique du `/` dans le nom, lookup via `GET /secrets?path=<parent>`,
puis opération via `/secrets/by-id/<sid>`.

## Compatibilité

- Go 1.21+
- Crypto AES-256-GCM via la bibliothèque standard (`crypto/aes`, `crypto/cipher`)
- Pas de dépendance externe au-delà de `github.com/google/uuid`

## Note sur le statut MVP

Cette première version (0.1.0) est un MVP qui supporte les opérations CRUD
de secrets et la résolution path-style. Les fonctionnalités avancées
(placeholders, générateurs, rotation, gestion d'API keys) sont prévues
pour les versions ultérieures.
