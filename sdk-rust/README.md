# Harpocrate SDK — Rust

Client zero-knowledge pour [Harpocrate Vault](https://github.com/gaelgael5/harpocrate).

Le SDK déchiffre **côté client** : le serveur ne voit jamais les valeurs en clair.
Crypto : AES-256-GCM, format de blob `nonce(12) || ciphertext || tag(16)` —
identique au SDK Python.

## Installation

```toml
# Cargo.toml
[dependencies]
harpocrate = "0.1"
tokio = { version = "1", features = ["rt-multi-thread", "macros"] }
```

## Usage

```rust
use harpocrate::VaultClient;

#[tokio::main]
async fn main() -> Result<(), harpocrate::HarpocrateError> {
    let client = VaultClient::new("hrpv_1_...", "https://vault.yoops.org").await?;

    // Lire un secret
    let value = client.get_secret("ANTHROPIC_API_KEY").await?;
    println!("{value}");

    // Lister
    for s in client.list_secrets().await?.secrets {
        println!("{} (placeholder={})", s.name, s.is_placeholder);
    }

    // Créer
    let _id = client.create_secret("MY_KEY", "secret-value").await?;

    // Mettre à jour
    let _gen = client.put_secret("MY_KEY", "new-value").await?;

    // Supprimer
    client.delete_secret("MY_KEY").await?;

    Ok(())
}
```

## Périmètre v0.1.0

- ✅ Parsing token `hrpv_*` (format identique au SDK Python)
- ✅ Crypto AES-256-GCM (encrypt/decrypt)
- ✅ HTTP client (reqwest + rustls)
- ✅ Get / List / Create / Put / Delete secrets
- ✅ Cache wallet_key thread-safe
- ✅ Encodage URL pour secrets path-style (`/folder/name`)
- ❌ Placeholders + générateurs (futur)
- ❌ Détection rotation auth_error (LOT 22, futur portage Rust)

## Tests

```bash
cargo test
```

## Publication crates.io

À effectuer manuellement par le mainteneur via `cargo publish` (credentials externes).
