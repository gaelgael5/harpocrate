//! # Harpocrate SDK Rust
//!
//! Client zero-knowledge pour [Harpocrate Vault](https://github.com/gaelgael5/harpocrate).
//!
//! Le SDK déchiffre côté client : le serveur ne voit jamais les valeurs en clair.
//!
//! ```no_run
//! use harpocrate::VaultClient;
//!
//! # async fn run() -> Result<(), harpocrate::HarpocrateError> {
//! let client = VaultClient::new("hrpv_1_...", "https://vault.yoops.org").await?;
//! let value = client.get_secret("ANTHROPIC_API_KEY").await?;
//! println!("{}", value);
//! # Ok(())
//! # }
//! ```

mod client;
mod crypto;
mod error;
mod token;
mod types;

pub use client::VaultClient;
pub use crypto::{aes_gcm_decrypt, aes_gcm_encrypt};
pub use error::HarpocrateError;
pub use token::{ParsedToken, parse_token};
pub use types::{ApiKeyInfo, SecretInfo, SecretListResponse, WalletInfo};
