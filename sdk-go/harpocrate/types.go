package harpocrate

import "github.com/google/uuid"

// SecretInfo représente un secret sans sa valeur (sortie de list).
type SecretInfo struct {
	ID                 uuid.UUID `json:"id"`
	Name               string    `json:"name"`
	Description        *string   `json:"description,omitempty"`
	Tags               []string  `json:"tags,omitempty"`
	IsPlaceholder      bool      `json:"is_placeholder,omitempty"`
	GenerationVersion  int64     `json:"generation_version,omitempty"`
}

// SecretListResponse encapsule la réponse de GET /secrets.
type SecretListResponse struct {
	Secrets    []SecretInfo `json:"secrets"`
	NextCursor *string      `json:"next_cursor,omitempty"`
}

// WalletInfo représente un coffre avec ses métadonnées (sans secrets).
type WalletInfo struct {
	ID          uuid.UUID `json:"id"`
	Name        string    `json:"name"`
	Description *string   `json:"description,omitempty"`
}

// APIKeyInfo représente le contexte d'authentification courant.
type APIKeyInfo struct {
	APIKeyID    uuid.UUID
	WalletID    uuid.UUID
	Permissions uint8
	Exp         uint64
}
