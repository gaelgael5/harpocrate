package harpocrate

import (
	"encoding/base32"
	"encoding/base64"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
)

// Format du token : hrpv_<v>_<id_b32>_<exp_b36>_<perms_hex>_<auth_b64>_<dkey_b64>_<hmac_b64>
// Identique aux SDK Python/Rust/TS/C#.
const (
	tokenPrefix    = "hrpv"
	tokenVersion   = "1"
	idB32Len       = 26
	authSecretLen  = 43
	dkeyLen        = 43
	hmacLen        = 22
	permsMaxValue  = 0x3F
	dkeyBytesLen   = 32
)

// ParsedToken représente un token Harpocrate décodé.
type ParsedToken struct {
	Version       string
	APIKeyID      uuid.UUID
	Exp           uint64 // 0 = pas d'expiration
	Permissions   uint8
	AuthSecretB64 string
	DecryptionKey [32]byte
	DkeyB64       string
	HmacB64       string
}

// ParseToken décode un token hrpv_*. Lève InvalidTokenError ou TokenExpiredError.
func ParseToken(token string) (*ParsedToken, error) {
	if !strings.HasPrefix(token, tokenPrefix+"_") {
		return nil, &InvalidTokenError{Reason: "invalid_prefix"}
	}

	// Les 3 derniers champs (auth, dkey, hmac) ont des longueurs fixes.
	// On parse positionnellement depuis la fin.
	suffixLen := authSecretLen + 1 + dkeyLen + 1 + hmacLen
	minLen := len(tokenPrefix) + 1 + 1 + 1 + idB32Len + 1 + 1 + 1 + 2 + 1 + suffixLen
	if len(token) < minLen {
		return nil, &InvalidTokenError{Reason: "too_short"}
	}

	total := len(token)
	hmacB64 := token[total-hmacLen:]
	if token[total-hmacLen-1] != '_' {
		return nil, &InvalidTokenError{Reason: "malformed"}
	}
	dkeyEnd := hmacLen + 1 + dkeyLen
	dkeyB64 := token[total-dkeyEnd : total-hmacLen-1]
	if token[total-dkeyEnd-1] != '_' {
		return nil, &InvalidTokenError{Reason: "malformed"}
	}
	authEnd := dkeyEnd + 1 + authSecretLen
	authB64 := token[total-authEnd : total-dkeyEnd-1]
	if token[total-authEnd-1] != '_' {
		return nil, &InvalidTokenError{Reason: "malformed"}
	}

	prefixPart := token[:total-suffixLen-1]
	parts := strings.Split(prefixPart, "_")
	if len(parts) != 5 {
		return nil, &InvalidTokenError{Reason: "malformed_prefix"}
	}
	prefix, version, idB32, expB36, permsHex := parts[0], parts[1], parts[2], parts[3], parts[4]

	if prefix != tokenPrefix {
		return nil, &InvalidTokenError{Reason: "invalid_prefix"}
	}
	if version != tokenVersion {
		return nil, &InvalidTokenError{Reason: "unsupported_version"}
	}
	if len(idB32) != idB32Len {
		return nil, &InvalidTokenError{Reason: "invalid_id_encoding"}
	}

	// UUID : 26 chars base32 lowercase → 16 bytes
	padded := strings.ToUpper(idB32) + "======"
	idBytes, err := base32.StdEncoding.DecodeString(padded[:32])
	if err != nil {
		return nil, &InvalidTokenError{Reason: "invalid_id_encoding"}
	}
	apiKeyID, err := uuid.FromBytes(idBytes)
	if err != nil {
		return nil, &InvalidTokenError{Reason: "invalid_id_encoding"}
	}

	exp, err := strconv.ParseUint(expB36, 36, 64)
	if err != nil {
		return nil, &InvalidTokenError{Reason: "invalid_exp_encoding"}
	}
	perms64, err := strconv.ParseUint(permsHex, 16, 8)
	if err != nil {
		return nil, &InvalidTokenError{Reason: "invalid_perms_encoding"}
	}
	if perms64 > permsMaxValue {
		return nil, &InvalidTokenError{Reason: "invalid_perms_value"}
	}

	dkeyBytes, err := base64.RawURLEncoding.DecodeString(dkeyB64)
	if err != nil {
		// retry with padding
		dkeyBytes, err = base64.URLEncoding.DecodeString(dkeyB64 + "==")
		if err != nil {
			return nil, &InvalidTokenError{Reason: "invalid_dkey_encoding"}
		}
	}
	if len(dkeyBytes) != dkeyBytesLen {
		return nil, &InvalidTokenError{Reason: "invalid_dkey_length"}
	}
	var dkey [32]byte
	copy(dkey[:], dkeyBytes)

	if exp != 0 {
		now := uint64(time.Now().Unix())
		if exp < now {
			return nil, &TokenExpiredError{}
		}
	}

	return &ParsedToken{
		Version:       version,
		APIKeyID:      apiKeyID,
		Exp:           exp,
		Permissions:   uint8(perms64),
		AuthSecretB64: authB64,
		DecryptionKey: dkey,
		DkeyB64:       dkeyB64,
		HmacB64:       hmacB64,
	}, nil
}
