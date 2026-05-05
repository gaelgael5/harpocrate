use serde::{Deserialize, Serialize};
use uuid::Uuid;

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct SecretInfo {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub tags: Vec<String>,
    #[serde(default)]
    pub is_placeholder: bool,
    #[serde(default)]
    pub generation_version: i64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SecretListResponse {
    #[serde(default)]
    pub secrets: Vec<SecretInfo>,
    #[serde(default)]
    pub next_cursor: Option<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct WalletInfo {
    pub id: Uuid,
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
}

#[derive(Debug, Clone)]
pub struct ApiKeyInfo {
    pub api_key_id: Uuid,
    pub wallet_id: Uuid,
    pub permissions: u8,
    pub exp: u64,
}
