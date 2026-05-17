package harpocrate

import (
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"fmt"
)

const (
	nonceLen = 12
	tagLen   = 16
)

// AESGCMEncrypt chiffre `plaintext` avec AES-256-GCM et retourne
// `nonce(12) || ciphertext || tag(16)`.
func AESGCMEncrypt(plaintext, key []byte) ([]byte, error) {
	if len(key) != 32 {
		return nil, &VaultDecryptionError{Reason: fmt.Sprintf("key must be 32 bytes, got %d", len(key))}
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, &VaultDecryptionError{Reason: "aes init: " + err.Error()}
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, &VaultDecryptionError{Reason: "gcm init: " + err.Error()}
	}
	nonce := make([]byte, nonceLen)
	if _, err := rand.Read(nonce); err != nil {
		return nil, &VaultDecryptionError{Reason: "nonce: " + err.Error()}
	}
	ct := aead.Seal(nil, nonce, plaintext, nil)
	out := make([]byte, 0, nonceLen+len(ct))
	out = append(out, nonce...)
	out = append(out, ct...)
	return out, nil
}

// AESGCMDecrypt déchiffre un blob `nonce(12) || ciphertext || tag(16)`.
func AESGCMDecrypt(blob, key []byte) ([]byte, error) {
	if len(key) != 32 {
		return nil, &VaultDecryptionError{Reason: fmt.Sprintf("key must be 32 bytes, got %d", len(key))}
	}
	if len(blob) < nonceLen+tagLen {
		return nil, &VaultDecryptionError{Reason: fmt.Sprintf("blob too short: %d bytes", len(blob))}
	}
	block, err := aes.NewCipher(key)
	if err != nil {
		return nil, &VaultDecryptionError{Reason: "aes init: " + err.Error()}
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		return nil, &VaultDecryptionError{Reason: "gcm init: " + err.Error()}
	}
	plain, err := aead.Open(nil, blob[:nonceLen], blob[nonceLen:], nil)
	if err != nil {
		return nil, &VaultDecryptionError{Reason: "invalid tag or wrong key: " + err.Error()}
	}
	return plain, nil
}
