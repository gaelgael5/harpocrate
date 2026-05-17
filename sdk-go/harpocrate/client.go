package harpocrate

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
)

const defaultTimeout = 30 * time.Second

// VaultClient est le client haut-niveau Harpocrate.
type VaultClient struct {
	parsed    *ParsedToken
	baseURL   string
	http      *http.Client
	authHdr   string
	walletID  uuid.UUID
	wkMu      sync.Mutex
	walletKey []byte // déchiffrée, 32 bytes, nil tant que pas résolue
}

// NewVaultClient crée un client + résout immédiatement le wallet_id.
func NewVaultClient(ctx context.Context, token, baseURL string) (*VaultClient, error) {
	parsed, err := ParseToken(token)
	if err != nil {
		return nil, err
	}
	c := &VaultClient{
		parsed:  parsed,
		baseURL: strings.TrimRight(baseURL, "/"),
		http:    &http.Client{Timeout: defaultTimeout},
		authHdr: "Bearer " + token,
	}
	// Résolution du wallet_id via /api-keys/<id>/wallet-id
	var widResp struct {
		WalletID string `json:"wallet_id"`
	}
	if err := c.getJSON(ctx, fmt.Sprintf("/v1/api-keys/%s/wallet-id", parsed.APIKeyID), &widResp); err != nil {
		return nil, err
	}
	wid, err := uuid.Parse(widResp.WalletID)
	if err != nil {
		return nil, &InvalidTokenError{Reason: "invalid_wallet_id: " + err.Error()}
	}
	c.walletID = wid
	return c, nil
}

// WalletID retourne l'UUID du coffre associé au token.
func (c *VaultClient) WalletID() uuid.UUID { return c.walletID }

// Whoami retourne le contexte d'authentification courant.
func (c *VaultClient) Whoami() APIKeyInfo {
	return APIKeyInfo{
		APIKeyID:    c.parsed.APIKeyID,
		WalletID:    c.walletID,
		Permissions: c.parsed.Permissions,
		Exp:         c.parsed.Exp,
	}
}

// ListSecrets liste les secrets du coffre (sans valeurs).
func (c *VaultClient) ListSecrets(ctx context.Context) (*SecretListResponse, error) {
	var resp SecretListResponse
	err := c.getJSON(ctx, fmt.Sprintf("/v1/wallets/%s/secrets", c.walletID), &resp)
	if err != nil {
		return nil, err
	}
	return &resp, nil
}

// GetSecret récupère et déchiffre la valeur d'un secret.
// Supporte les noms path-style (contenant '/') via résolution by-id.
func (c *VaultClient) GetSecret(ctx context.Context, name string) (string, error) {
	path, err := c.pathForOp(ctx, name)
	if err != nil {
		return "", err
	}
	var resp struct {
		EncryptedValue string `json:"encrypted_value"`
	}
	if err := c.getJSON(ctx, path, &resp); err != nil {
		return "", err
	}
	wk, err := c.getWalletKey(ctx)
	if err != nil {
		return "", err
	}
	enc, err := base64.StdEncoding.DecodeString(resp.EncryptedValue)
	if err != nil {
		return "", &VaultDecryptionError{Reason: "base64: " + err.Error()}
	}
	plain, err := AESGCMDecrypt(enc, wk)
	if err != nil {
		return "", err
	}
	return string(plain), nil
}

// CreateSecret crée un nouveau secret avec sa valeur chiffrée. Retourne son UUID.
func (c *VaultClient) CreateSecret(ctx context.Context, name, value string) (uuid.UUID, error) {
	wk, err := c.getWalletKey(ctx)
	if err != nil {
		return uuid.Nil, err
	}
	enc, err := AESGCMEncrypt([]byte(value), wk)
	if err != nil {
		return uuid.Nil, err
	}
	body := map[string]string{
		"name":            name,
		"encrypted_value": base64.StdEncoding.EncodeToString(enc),
	}
	var resp struct {
		SecretID string `json:"secret_id"`
	}
	if err := c.postJSON(ctx, fmt.Sprintf("/v1/wallets/%s/secrets", c.walletID), body, &resp); err != nil {
		return uuid.Nil, err
	}
	return uuid.Parse(resp.SecretID)
}

// PutSecret remplace la valeur d'un secret existant. Retourne la nouvelle generation_version.
func (c *VaultClient) PutSecret(ctx context.Context, name, value string) (int64, error) {
	wk, err := c.getWalletKey(ctx)
	if err != nil {
		return 0, err
	}
	enc, err := AESGCMEncrypt([]byte(value), wk)
	if err != nil {
		return 0, err
	}
	body := map[string]string{
		"encrypted_value": base64.StdEncoding.EncodeToString(enc),
	}
	path, err := c.pathForOp(ctx, name)
	if err != nil {
		return 0, err
	}
	var resp struct {
		GenerationVersion int64 `json:"generation_version"`
	}
	if err := c.putJSON(ctx, path, body, &resp); err != nil {
		return 0, err
	}
	return resp.GenerationVersion, nil
}

// DeleteSecret supprime un secret. Supporte les noms path-style.
func (c *VaultClient) DeleteSecret(ctx context.Context, name string) error {
	path, err := c.pathForOp(ctx, name)
	if err != nil {
		return err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodDelete, c.baseURL+path, nil)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", c.authHdr)
	r, err := c.http.Do(req)
	if err != nil {
		return err
	}
	defer r.Body.Close()
	if r.StatusCode == http.StatusNotFound {
		return &SecretNotFoundError{Name: name}
	}
	if r.StatusCode >= 300 {
		body, _ := io.ReadAll(r.Body)
		return &VaultHTTPError{Status: r.StatusCode, Body: string(body)}
	}
	return nil
}

// ─── Internals ────────────────────────────────────────────────────────────

func (c *VaultClient) secretURLByName(name string) string {
	normalized := name
	if strings.Contains(name, "/") && !strings.HasPrefix(name, "/") {
		normalized = "/" + name
	}
	return fmt.Sprintf("/v1/wallets/%s/secrets/%s", c.walletID, url.PathEscape(normalized))
}

func (c *VaultClient) secretURLByID(sid uuid.UUID) string {
	return fmt.Sprintf("/v1/wallets/%s/secrets/by-id/%s", c.walletID, sid)
}

// resolveIDIfPathstyle résout l'UUID d'un secret nommé en path-style (`/foo/bar`).
// Retourne uuid.Nil + nil pour les noms plats (le caller utilisera la route name-based).
// Évite la dépendance fragile au comportement des reverse proxies sur les '/'
// URL-encodés (%2F) — pattern aligné sur SDK Python 0.6.0.
func (c *VaultClient) resolveIDIfPathstyle(ctx context.Context, name string) (uuid.UUID, error) {
	if !strings.Contains(name, "/") {
		return uuid.Nil, nil
	}
	normalized := name
	if !strings.HasPrefix(name, "/") {
		normalized = "/" + name
	}
	lastSlash := strings.LastIndex(normalized, "/")
	var parentPath string
	if lastSlash == 0 {
		parentPath = "/"
	} else {
		parentPath = normalized[:lastSlash] + "/"
	}
	listPath := fmt.Sprintf("/v1/wallets/%s/secrets?path=%s", c.walletID, url.QueryEscape(parentPath))
	var listing SecretListResponse
	if err := c.getJSON(ctx, listPath, &listing); err != nil {
		return uuid.Nil, err
	}
	for _, s := range listing.Secrets {
		if s.Name == normalized {
			return s.ID, nil
		}
	}
	return uuid.Nil, &SecretNotFoundError{Name: name}
}

// pathForOp retourne le chemin d'opération unitaire :
// /by-id/<sid> pour les noms path-style, /<encoded-name> pour les noms plats.
func (c *VaultClient) pathForOp(ctx context.Context, name string) (string, error) {
	sid, err := c.resolveIDIfPathstyle(ctx, name)
	if err != nil {
		return "", err
	}
	if sid == uuid.Nil {
		return c.secretURLByName(name), nil
	}
	return c.secretURLByID(sid), nil
}

func (c *VaultClient) getWalletKey(ctx context.Context) ([]byte, error) {
	c.wkMu.Lock()
	if c.walletKey != nil {
		k := c.walletKey
		c.wkMu.Unlock()
		return k, nil
	}
	c.wkMu.Unlock()
	var grant struct {
		EncryptedWalletKey string `json:"encrypted_wallet_key"`
	}
	if err := c.getJSON(ctx, fmt.Sprintf("/v1/wallets/%s/my-api-key-grant", c.walletID), &grant); err != nil {
		return nil, err
	}
	enc, err := base64.StdEncoding.DecodeString(grant.EncryptedWalletKey)
	if err != nil {
		return nil, &VaultDecryptionError{Reason: "base64 grant: " + err.Error()}
	}
	wk, err := AESGCMDecrypt(enc, c.parsed.DecryptionKey[:])
	if err != nil {
		return nil, err
	}
	if len(wk) != 32 {
		return nil, &VaultDecryptionError{Reason: fmt.Sprintf("wallet_key not 32 bytes: %d", len(wk))}
	}
	c.wkMu.Lock()
	c.walletKey = wk
	c.wkMu.Unlock()
	return wk, nil
}

// ─── HTTP helpers ────────────────────────────────────────────────────────

func (c *VaultClient) doRequest(ctx context.Context, method, path string, body []byte) (*http.Response, error) {
	var bodyReader io.Reader
	if body != nil {
		bodyReader = bytes.NewReader(body)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, bodyReader)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Authorization", c.authHdr)
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	return c.http.Do(req)
}

func (c *VaultClient) getJSON(ctx context.Context, path string, out any) error {
	r, err := c.doRequest(ctx, http.MethodGet, path, nil)
	if err != nil {
		return err
	}
	defer r.Body.Close()
	return decodeOrErr(r, out)
}

func (c *VaultClient) postJSON(ctx context.Context, path string, body, out any) error {
	b, err := json.Marshal(body)
	if err != nil {
		return err
	}
	r, err := c.doRequest(ctx, http.MethodPost, path, b)
	if err != nil {
		return err
	}
	defer r.Body.Close()
	return decodeOrErr(r, out)
}

func (c *VaultClient) putJSON(ctx context.Context, path string, body, out any) error {
	b, err := json.Marshal(body)
	if err != nil {
		return err
	}
	r, err := c.doRequest(ctx, http.MethodPut, path, b)
	if err != nil {
		return err
	}
	defer r.Body.Close()
	return decodeOrErr(r, out)
}

func decodeOrErr(r *http.Response, out any) error {
	if r.StatusCode == http.StatusNotFound {
		body, _ := io.ReadAll(r.Body)
		return &SecretNotFoundError{Name: string(body)}
	}
	if r.StatusCode >= 300 {
		body, _ := io.ReadAll(r.Body)
		return &VaultHTTPError{Status: r.StatusCode, Body: string(body)}
	}
	if r.StatusCode == http.StatusNoContent || out == nil {
		return nil
	}
	return json.NewDecoder(r.Body).Decode(out)
}
