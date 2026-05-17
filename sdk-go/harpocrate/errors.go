// Package harpocrate — SDK Go zero-knowledge pour Harpocrate Vault.
package harpocrate

import "fmt"

// InvalidTokenError signale un token hrpv_* malformé ou non parsable.
type InvalidTokenError struct{ Reason string }

func (e *InvalidTokenError) Error() string { return "invalid token: " + e.Reason }

// TokenExpiredError signale un token dont la date d'expiration est dépassée.
type TokenExpiredError struct{}

func (e *TokenExpiredError) Error() string { return "token expired" }

// SecretNotFoundError signale un secret introuvable sur le serveur.
type SecretNotFoundError struct{ Name string }

func (e *SecretNotFoundError) Error() string {
	return fmt.Sprintf("secret not found: %s", e.Name)
}

// VaultHTTPError signale une erreur HTTP non-404 retournée par le serveur.
type VaultHTTPError struct {
	Status int
	Body   string
}

func (e *VaultHTTPError) Error() string {
	return fmt.Sprintf("vault http error %d: %s", e.Status, e.Body)
}

// VaultDecryptionError signale un échec de déchiffrement (clé invalide,
// blob corrompu, base64 malformé, etc.).
type VaultDecryptionError struct{ Reason string }

func (e *VaultDecryptionError) Error() string { return "decryption failed: " + e.Reason }
