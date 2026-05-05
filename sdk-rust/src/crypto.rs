//! AES-256-GCM encrypt/decrypt — format `nonce(12) || ciphertext || tag(16)`.

use aes_gcm::{
    Aes256Gcm, Nonce,
    aead::{Aead, AeadCore, KeyInit, OsRng},
};

use crate::error::HarpocrateError;

const NONCE_LEN: usize = 12;
const TAG_LEN: usize = 16;

/// Chiffre `plaintext` avec AES-256-GCM. Retourne `nonce || ciphertext+tag`.
pub fn aes_gcm_encrypt(plaintext: &[u8], key: &[u8]) -> Result<Vec<u8>, HarpocrateError> {
    if key.len() != 32 {
        return Err(HarpocrateError::Decryption(format!(
            "key must be 32 bytes, got {}",
            key.len()
        )));
    }
    let cipher = Aes256Gcm::new_from_slice(key)
        .map_err(|e| HarpocrateError::Decryption(format!("init: {e}")))?;
    let nonce = Aes256Gcm::generate_nonce(&mut OsRng);
    let ciphertext = cipher
        .encrypt(&nonce, plaintext)
        .map_err(|e| HarpocrateError::Decryption(format!("encrypt: {e}")))?;
    let mut out = Vec::with_capacity(NONCE_LEN + ciphertext.len());
    out.extend_from_slice(&nonce);
    out.extend_from_slice(&ciphertext);
    Ok(out)
}

/// Déchiffre un blob `nonce(12) || ciphertext || tag(16)` avec AES-256-GCM.
pub fn aes_gcm_decrypt(blob: &[u8], key: &[u8]) -> Result<Vec<u8>, HarpocrateError> {
    if key.len() != 32 {
        return Err(HarpocrateError::Decryption(format!(
            "key must be 32 bytes, got {}",
            key.len()
        )));
    }
    if blob.len() < NONCE_LEN + TAG_LEN {
        return Err(HarpocrateError::Decryption(format!(
            "blob too short: {} bytes",
            blob.len()
        )));
    }
    let cipher = Aes256Gcm::new_from_slice(key)
        .map_err(|e| HarpocrateError::Decryption(format!("init: {e}")))?;
    let nonce = Nonce::from_slice(&blob[..NONCE_LEN]);
    cipher
        .decrypt(nonce, &blob[NONCE_LEN..])
        .map_err(|e| HarpocrateError::Decryption(format!("invalid tag or wrong key: {e}")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_round_trip() {
        let key = [42u8; 32];
        let plain = b"hello vault";
        let blob = aes_gcm_encrypt(plain, &key).unwrap();
        let decrypted = aes_gcm_decrypt(&blob, &key).unwrap();
        assert_eq!(decrypted, plain);
    }

    #[test]
    fn test_decrypt_with_wrong_key_fails() {
        let blob = aes_gcm_encrypt(b"x", &[1u8; 32]).unwrap();
        let err = aes_gcm_decrypt(&blob, &[2u8; 32]).unwrap_err();
        assert!(matches!(err, HarpocrateError::Decryption(_)));
    }

    #[test]
    fn test_rejects_short_key() {
        let err = aes_gcm_encrypt(b"x", &[0u8; 16]).unwrap_err();
        assert!(matches!(err, HarpocrateError::Decryption(_)));
    }

    #[test]
    fn test_rejects_short_blob() {
        let err = aes_gcm_decrypt(&[0u8; 5], &[0u8; 32]).unwrap_err();
        assert!(matches!(err, HarpocrateError::Decryption(_)));
    }
}
