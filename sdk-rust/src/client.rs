//! Client haut-niveau Harpocrate Vault.

use std::sync::Mutex;

use base64::{Engine as _, engine::general_purpose::STANDARD};
use reqwest::{Client, StatusCode, header};
use serde::Deserialize;
use serde_json::json;
use uuid::Uuid;

use crate::crypto::{aes_gcm_decrypt, aes_gcm_encrypt};
use crate::error::HarpocrateError;
use crate::token::{ParsedToken, parse_token};
use crate::types::{ApiKeyInfo, SecretInfo, SecretListResponse, WalletInfo};

pub struct VaultClient {
    parsed: ParsedToken,
    base_url: String,
    http: Client,
    wallet_id: Uuid,
    /// Cache de la wallet_key déchiffrée (thread-safe).
    wallet_key: Mutex<Option<[u8; 32]>>,
}

impl VaultClient {
    /// Crée un client + résout immédiatement le wallet_id depuis l'API.
    pub async fn new(token: &str, base_url: &str) -> Result<Self, HarpocrateError> {
        let parsed = parse_token(token)?;
        let mut headers = header::HeaderMap::new();
        let auth = format!("Bearer {token}");
        headers.insert(
            header::AUTHORIZATION,
            header::HeaderValue::from_str(&auth)
                .map_err(|e| HarpocrateError::InvalidToken(e.to_string()))?,
        );
        let http = Client::builder()
            .default_headers(headers)
            .timeout(std::time::Duration::from_secs(30))
            .build()?;

        let base = base_url.trim_end_matches('/').to_string();
        let wid_url = format!("{base}/v1/api-keys/{}/wallet-id", parsed.api_key_id);
        let wid_resp: WalletIdResp = get_json(&http, &wid_url).await?;
        let wallet_id = Uuid::parse_str(&wid_resp.wallet_id)
            .map_err(|e| HarpocrateError::InvalidToken(e.to_string()))?;

        Ok(Self {
            parsed,
            base_url: base,
            http,
            wallet_id,
            wallet_key: Mutex::new(None),
        })
    }

    pub fn wallet_id(&self) -> Uuid {
        self.wallet_id
    }

    pub fn whoami(&self) -> ApiKeyInfo {
        ApiKeyInfo {
            api_key_id: self.parsed.api_key_id,
            wallet_id: self.wallet_id,
            permissions: self.parsed.permissions,
            exp: self.parsed.exp,
        }
    }

    /// Récupère + déchiffre la wallet_key (mise en cache).
    async fn wallet_key(&self) -> Result<[u8; 32], HarpocrateError> {
        if let Some(k) = *self.wallet_key.lock().expect("poisoned mutex") {
            return Ok(k);
        }
        let url = format!(
            "{}/v1/wallets/{}/my-api-key-grant",
            self.base_url, self.wallet_id
        );
        let grant: GrantResp = get_json(&self.http, &url).await?;
        let enc = STANDARD
            .decode(&grant.encrypted_wallet_key)
            .map_err(|e| HarpocrateError::Decryption(format!("base64: {e}")))?;
        let wk = aes_gcm_decrypt(&enc, &self.parsed.decryption_key)?;
        if wk.len() != 32 {
            return Err(HarpocrateError::Decryption("wallet_key not 32 bytes".into()));
        }
        let mut k = [0u8; 32];
        k.copy_from_slice(&wk);
        *self.wallet_key.lock().expect("poisoned mutex") = Some(k);
        Ok(k)
    }

    fn secret_url_by_name(&self, name: &str) -> String {
        let normalized = if name.contains('/') && !name.starts_with('/') {
            format!("/{name}")
        } else {
            name.to_string()
        };
        let encoded = url_encode(&normalized);
        format!(
            "{}/v1/wallets/{}/secrets/{}",
            self.base_url, self.wallet_id, encoded
        )
    }

    fn secret_url_by_id(&self, sid: &Uuid) -> String {
        format!(
            "{}/v1/wallets/{}/secrets/by-id/{}",
            self.base_url, self.wallet_id, sid
        )
    }

    /// Si `name` contient `/` (path-style), résout l'UUID via
    /// `GET /v1/wallets/{wid}/secrets?path=<parent>` puis filtre par nom.
    /// Retourne `Ok(None)` pour les noms plats (le caller utilisera la
    /// route name-based).
    ///
    /// Cette stratégie évite la dépendance fragile au comportement des
    /// reverse proxies vis-à-vis des `/` URL-encodés (`%2F`), qui sont
    /// refusés par défaut par nginx/Caddy avec certaines configurations.
    /// Pattern aligné sur celui du SDK Python depuis la 0.6.0.
    async fn resolve_id_if_pathstyle(
        &self,
        name: &str,
    ) -> Result<Option<Uuid>, HarpocrateError> {
        if !name.contains('/') {
            return Ok(None);
        }
        let normalized = if name.starts_with('/') {
            name.to_string()
        } else {
            format!("/{name}")
        };
        let parent_path = match normalized.rsplit_once('/') {
            Some((parent, _)) if parent.is_empty() => "/".to_string(),
            Some((parent, _)) => format!("{parent}/"),
            None => "/".to_string(),
        };
        let url = format!(
            "{}/v1/wallets/{}/secrets?path={}",
            self.base_url,
            self.wallet_id,
            url_encode(&parent_path),
        );
        let listing: SecretListResponse = get_json(&self.http, &url).await?;
        listing
            .secrets
            .iter()
            .find(|s| s.name == normalized)
            .map(|s| Some(s.id))
            .ok_or_else(|| HarpocrateError::SecretNotFound(name.to_string()))
    }

    /// Retourne l'URL d'opération unitaire (GET/PUT/DELETE) pour un secret :
    /// `/by-id/{sid}` si nom path-style (`name` contient `/`), `/{name}` sinon.
    async fn path_for_op(&self, name: &str) -> Result<String, HarpocrateError> {
        match self.resolve_id_if_pathstyle(name).await? {
            Some(sid) => Ok(self.secret_url_by_id(&sid)),
            None => Ok(self.secret_url_by_name(name)),
        }
    }

    pub async fn list_secrets(&self) -> Result<SecretListResponse, HarpocrateError> {
        let url = format!("{}/v1/wallets/{}/secrets", self.base_url, self.wallet_id);
        get_json(&self.http, &url).await
    }

    pub async fn get_secret(&self, name: &str) -> Result<String, HarpocrateError> {
        let url = self.path_for_op(name).await?;
        let resp: SecretResp = get_json(&self.http, &url).await?;
        let wk = self.wallet_key().await?;
        let enc = STANDARD
            .decode(&resp.encrypted_value)
            .map_err(|e| HarpocrateError::Decryption(format!("base64: {e}")))?;
        let plain = aes_gcm_decrypt(&enc, &wk)?;
        String::from_utf8(plain)
            .map_err(|e| HarpocrateError::Decryption(format!("utf8: {e}")))
    }

    pub async fn create_secret(
        &self,
        name: &str,
        value: &str,
    ) -> Result<Uuid, HarpocrateError> {
        let wk = self.wallet_key().await?;
        let enc = aes_gcm_encrypt(value.as_bytes(), &wk)?;
        let body = json!({
            "name": name,
            "encrypted_value": STANDARD.encode(&enc),
        });
        let url = format!("{}/v1/wallets/{}/secrets", self.base_url, self.wallet_id);
        let resp: CreateSecretResp = post_json(&self.http, &url, &body).await?;
        Uuid::parse_str(&resp.secret_id)
            .map_err(|e| HarpocrateError::Decryption(format!("uuid: {e}")))
    }

    pub async fn put_secret(
        &self,
        name: &str,
        value: &str,
    ) -> Result<i64, HarpocrateError> {
        let wk = self.wallet_key().await?;
        let enc = aes_gcm_encrypt(value.as_bytes(), &wk)?;
        let body = json!({"encrypted_value": STANDARD.encode(&enc)});
        let url = self.path_for_op(name).await?;
        let resp: PutSecretResp = put_json(&self.http, &url, &body).await?;
        Ok(resp.generation_version)
    }

    pub async fn delete_secret(&self, name: &str) -> Result<(), HarpocrateError> {
        let url = self.path_for_op(name).await?;
        let r = self.http.delete(&url).send().await?;
        if !r.status().is_success() {
            return Err(HarpocrateError::Http {
                status: r.status().as_u16(),
                body: r.text().await.unwrap_or_default(),
            });
        }
        Ok(())
    }

    pub async fn wallet_info(&self) -> Result<WalletInfo, HarpocrateError> {
        let url = format!("{}/v1/wallets/{}", self.base_url, self.wallet_id);
        get_json(&self.http, &url).await
    }
}

// ─── Helpers HTTP ────────────────────────────────────────────────────────────

async fn get_json<T: for<'de> Deserialize<'de>>(
    http: &Client,
    url: &str,
) -> Result<T, HarpocrateError> {
    let r = http.get(url).send().await?;
    let status = r.status();
    if status == StatusCode::NOT_FOUND {
        return Err(HarpocrateError::SecretNotFound(url.to_string()));
    }
    if !status.is_success() {
        return Err(HarpocrateError::Http {
            status: status.as_u16(),
            body: r.text().await.unwrap_or_default(),
        });
    }
    r.json::<T>().await.map_err(Into::into)
}

async fn post_json<T: for<'de> Deserialize<'de>>(
    http: &Client,
    url: &str,
    body: &serde_json::Value,
) -> Result<T, HarpocrateError> {
    let r = http.post(url).json(body).send().await?;
    if !r.status().is_success() {
        return Err(HarpocrateError::Http {
            status: r.status().as_u16(),
            body: r.text().await.unwrap_or_default(),
        });
    }
    r.json::<T>().await.map_err(Into::into)
}

async fn put_json<T: for<'de> Deserialize<'de>>(
    http: &Client,
    url: &str,
    body: &serde_json::Value,
) -> Result<T, HarpocrateError> {
    let r = http.put(url).json(body).send().await?;
    if !r.status().is_success() {
        return Err(HarpocrateError::Http {
            status: r.status().as_u16(),
            body: r.text().await.unwrap_or_default(),
        });
    }
    r.json::<T>().await.map_err(Into::into)
}

fn url_encode(s: &str) -> String {
    // Encodage minimal pour les secrets path-style : on encode % et /.
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '/' => out.push_str("%2F"),
            '%' => out.push_str("%25"),
            ' ' => out.push_str("%20"),
            other if other.is_ascii_alphanumeric() => out.push(other),
            other if matches!(other, '-' | '_' | '.' | '~') => out.push(other),
            other => {
                let mut buf = [0u8; 4];
                for b in other.encode_utf8(&mut buf).as_bytes() {
                    out.push_str(&format!("%{:02X}", b));
                }
            }
        }
    }
    out
}

// ─── Réponses internes ───────────────────────────────────────────────────────

#[derive(Deserialize)]
struct WalletIdResp {
    wallet_id: String,
}

#[derive(Deserialize)]
struct GrantResp {
    encrypted_wallet_key: String,
}

#[derive(Deserialize)]
struct SecretResp {
    encrypted_value: String,
}

#[derive(Deserialize)]
struct CreateSecretResp {
    secret_id: String,
}

#[derive(Deserialize)]
struct PutSecretResp {
    generation_version: i64,
}
