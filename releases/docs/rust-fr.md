# SDK Rust

Client Rust zero-knowledge pour Harpocrate Vault. Compatible Rust 2021 edition.

Le SDK déchiffre les secrets côté client — le serveur ne voit jamais les valeurs en clair.

## Installation

Télécharger l'archive depuis cette page, extraire et ajouter au `Cargo.toml` via un `path` :

```bash
tar -xzf harpocrate-rust-sdk-0.2.0.tar.gz -C ./vendor/harpocrate
```

Puis dans `Cargo.toml` :

```toml
[dependencies]
harpocrate = { path = "./vendor/harpocrate" }
tokio = { version = "1", features = ["rt-multi-thread", "macros"] }
```

## Usage

```rust
use harpocrate::VaultClient;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let client = VaultClient::new(
        "hrpv_1_...",                  // ton API token
        "https://vault.example.com",
    ).await?;

    // Crée un secret
    let id = client.create_secret("DB_PASSWORD", "s3cret!").await?;
    println!("id = {}", id);

    // Récupère et déchiffre côté client
    let value = client.get_secret("DB_PASSWORD").await?;
    println!("value = {}", value);

    // Met à jour
    let gen = client.put_secret("DB_PASSWORD", "n3w-s3cret!").await?;
    println!("generation = {}", gen);

    // Supprime
    client.delete_secret("DB_PASSWORD").await?;

    Ok(())
}
```

## Secrets organisés en arborescence (path-style)

```rust
client.create_secret("/db/prod/password", "s3cret!").await?;
let value = client.get_secret("/db/prod/password").await?;
```

Depuis la version 0.2.0, le SDK utilise la résolution `/by-id/<uuid>` pour les
secrets path-style. Cela évite toute dépendance au comportement des reverse
proxies vis-à-vis des `/` URL-encodés (`%2F`).

## Compatibilité

- Rust 2021 edition (compilateur 1.65+)
- Runtime async basé sur tokio
- Crypto AES-256-GCM via le crate `aes-gcm`
- HTTP via `reqwest` avec TLS rustls

## Pour aller plus loin

Voir le [README complet du SDK](https://github.com/gaelgael5/harpocrate/tree/main/sdk-rust) sur GitHub.
