# Harpocrate SDK Go

Client Go zero-knowledge pour [Harpocrate Vault](https://github.com/gaelgael5/harpocrate).

Le SDK déchiffre les valeurs des secrets côté client — le serveur ne voit jamais les valeurs en clair.

## Installation

```bash
go get github.com/gaelgael5/harpocrate-sdk-go/harpocrate
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
        "hrpv_1_...", // ton API token
        "https://vault.example.com",
    )
    if err != nil {
        log.Fatal(err)
    }

    // Crée un secret avec un nom path-style (organisé en arborescence)
    id, _ := client.CreateSecret(ctx, "/db/prod/password", "s3cret!")
    fmt.Println("created:", id)

    // Récupère et déchiffre côté client
    value, _ := client.GetSecret(ctx, "/db/prod/password")
    fmt.Println("value:", value)

    // Met à jour
    gen, _ := client.PutSecret(ctx, "/db/prod/password", "n3w-s3cret!")
    fmt.Println("generation:", gen)

    // Supprime
    _ = client.DeleteSecret(ctx, "/db/prod/password")
}
```

## Support des secrets path-style

Les noms contenant `/` (ex: `db/prod/password`) sont supportés de manière
transparente. En interne, le SDK :

1. Détecte le `/` dans le nom
2. Liste les secrets du dossier parent via `GET /secrets?path=<parent>`
3. Trouve l'UUID correspondant
4. Effectue l'opération via les routes `/secrets/by-id/<sid>`

Cette stratégie évite la dépendance au comportement des reverse proxies vis-à-vis
des `/` URL-encodés (`%2F`) — pattern aligné sur le SDK Python 0.6.0.

## Compatibilité

- Go 1.21+
- Format de token `hrpv_*` identique aux SDK Python/Rust/TypeScript/C#
- Crypto AES-256-GCM (format `nonce(12) || ciphertext || tag(16)`)

## Tests

```bash
go test ./...
```

## Licence

MIT
