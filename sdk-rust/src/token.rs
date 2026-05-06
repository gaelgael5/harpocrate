//! Parsing du token `hrpv_v_id_exp_perms_auth_dkey_hmac` (LOT_09 — format identique au SDK Python).

use std::time::{SystemTime, UNIX_EPOCH};

use base32::Alphabet;
use base64::{Engine as _, engine::general_purpose::URL_SAFE_NO_PAD};
use uuid::Uuid;

use crate::error::HarpocrateError;

const TOKEN_PREFIX: &str = "hrpv";
const TOKEN_VERSION: &str = "1";
const ID_B32_LEN: usize = 26;
const AUTH_SECRET_LEN: usize = 43;
const DKEY_LEN: usize = 43;
const HMAC_LEN: usize = 22;

#[derive(Debug, Clone)]
pub struct ParsedToken {
    pub version: String,
    pub api_key_id: Uuid,
    /// Timestamp Unix d'expiration. 0 = pas d'expiration.
    pub exp: u64,
    /// Bitmap des permissions (max 0x3F).
    pub permissions: u8,
    pub auth_secret_b64: String,
    /// 32 bytes décodés depuis le champ dkey (clé AES-256 pour déchiffrer wallet_key).
    pub decryption_key: [u8; 32],
    pub dkey_b64: String,
    pub hmac_b64: String,
}

pub fn parse_token(token: &str) -> Result<ParsedToken, HarpocrateError> {
    if !token.starts_with(&format!("{TOKEN_PREFIX}_")) {
        return Err(HarpocrateError::InvalidToken("invalid_prefix".into()));
    }

    let suffix_len = AUTH_SECRET_LEN + 1 + DKEY_LEN + 1 + HMAC_LEN;
    let min_len = TOKEN_PREFIX.len() + 1 + 1 + 1 + ID_B32_LEN + 1 + 1 + 1 + 2 + 1 + suffix_len;
    if token.len() < min_len {
        return Err(HarpocrateError::InvalidToken("too_short".into()));
    }

    // Parsing positionnel depuis la fin (les 3 derniers champs ont des longueurs fixes).
    let total = token.len();
    let hmac_b64 = &token[total - HMAC_LEN..];
    if token.as_bytes()[total - HMAC_LEN - 1] != b'_' {
        return Err(HarpocrateError::InvalidToken("malformed".into()));
    }
    let dkey_end = HMAC_LEN + 1 + DKEY_LEN;
    let dkey_b64 = &token[total - dkey_end..total - HMAC_LEN - 1];
    if token.as_bytes()[total - dkey_end - 1] != b'_' {
        return Err(HarpocrateError::InvalidToken("malformed".into()));
    }
    let auth_end = dkey_end + 1 + AUTH_SECRET_LEN;
    let auth_secret_b64 = &token[total - auth_end..total - dkey_end - 1];
    if token.as_bytes()[total - auth_end - 1] != b'_' {
        return Err(HarpocrateError::InvalidToken("malformed".into()));
    }

    let prefix_part = &token[..total - suffix_len - 1];
    let parts: Vec<&str> = prefix_part.split('_').collect();
    if parts.len() != 5 {
        return Err(HarpocrateError::InvalidToken("malformed_prefix".into()));
    }
    let (prefix, version, id_b32, exp_b36, perms_hex) =
        (parts[0], parts[1], parts[2], parts[3], parts[4]);

    if prefix != TOKEN_PREFIX {
        return Err(HarpocrateError::InvalidToken("invalid_prefix".into()));
    }
    if version != TOKEN_VERSION {
        return Err(HarpocrateError::InvalidToken("unsupported_version".into()));
    }
    if id_b32.len() != ID_B32_LEN {
        return Err(HarpocrateError::InvalidToken("invalid_id_encoding".into()));
    }

    // Décodage UUID depuis base32 lowercase 26 chars
    let padded = format!("{}======", id_b32.to_uppercase());
    let id_bytes = base32::decode(Alphabet::Rfc4648 { padding: true }, &padded[..32])
        .ok_or_else(|| HarpocrateError::InvalidToken("invalid_id_encoding".into()))?;
    let api_key_id = Uuid::from_slice(&id_bytes)
        .map_err(|_| HarpocrateError::InvalidToken("invalid_id_encoding".into()))?;

    let exp = u64::from_str_radix(exp_b36, 36)
        .map_err(|_| HarpocrateError::InvalidToken("invalid_exp_encoding".into()))?;
    let perms = u8::from_str_radix(perms_hex, 16)
        .map_err(|_| HarpocrateError::InvalidToken("invalid_perms_encoding".into()))?;
    if perms > 0x3F {
        return Err(HarpocrateError::InvalidToken("invalid_perms_value".into()));
    }

    let dkey_padded = format!("{dkey_b64}==");
    let dkey_bytes = URL_SAFE_NO_PAD
        .decode(dkey_b64)
        .or_else(|_| base64::engine::general_purpose::URL_SAFE.decode(&dkey_padded))
        .map_err(|_| HarpocrateError::InvalidToken("invalid_dkey_encoding".into()))?;
    if dkey_bytes.len() != 32 {
        return Err(HarpocrateError::InvalidToken("invalid_dkey_length".into()));
    }
    let mut dkey = [0u8; 32];
    dkey.copy_from_slice(&dkey_bytes);

    if exp != 0 {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        if exp < now {
            return Err(HarpocrateError::TokenExpired);
        }
    }

    Ok(ParsedToken {
        version: version.into(),
        api_key_id,
        exp,
        permissions: perms,
        auth_secret_b64: auth_secret_b64.into(),
        decryption_key: dkey,
        dkey_b64: dkey_b64.into(),
        hmac_b64: hmac_b64.into(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rejects_invalid_prefix() {
        let err = parse_token("foo_bar").unwrap_err();
        assert!(matches!(err, HarpocrateError::InvalidToken(_)));
    }

    #[test]
    fn test_rejects_too_short() {
        let err = parse_token("hrpv_1_short").unwrap_err();
        assert!(matches!(err, HarpocrateError::InvalidToken(_)));
    }
}
