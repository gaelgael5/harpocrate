/**
 * Parsing du token `hrpv_v_id_exp_perms_auth_dkey_hmac` (format identique aux autres SDK).
 */
import { InvalidTokenError, TokenExpiredError } from './errors.js'

const PREFIX = 'hrpv'
const VERSION = '1'
const ID_B32_LEN = 26
const AUTH_SECRET_LEN = 43
const DKEY_LEN = 43
const HMAC_LEN = 22

export interface ParsedToken {
  version: string
  apiKeyId: string
  /** Timestamp Unix d'expiration. 0 = pas d'expiration. */
  exp: number
  /** Bitmap des permissions (max 0x3F). */
  permissions: number
  authSecretB64: string
  /** 32 bytes décodés depuis le champ dkey (clé AES-256 pour déchiffrer wallet_key). */
  decryptionKey: Uint8Array
  dkeyB64: string
  hmacB64: string
}

export function parseToken(token: string): ParsedToken {
  if (typeof token !== 'string' || !token.startsWith(`${PREFIX}_`)) {
    throw new InvalidTokenError('invalid_prefix', "Token must start with 'hrpv_'")
  }

  const suffixLen = AUTH_SECRET_LEN + 1 + DKEY_LEN + 1 + HMAC_LEN
  const minLen = PREFIX.length + 1 + 1 + 1 + ID_B32_LEN + 1 + 1 + 1 + 2 + 1 + suffixLen
  if (token.length < minLen) {
    throw new InvalidTokenError('invalid_format', 'Token is too short')
  }

  const total = token.length
  const hmacB64 = token.slice(total - HMAC_LEN)
  if (token[total - HMAC_LEN - 1] !== '_') {
    throw new InvalidTokenError('invalid_format', 'Malformed token structure')
  }
  const dkeyEnd = HMAC_LEN + 1 + DKEY_LEN
  const dkeyB64 = token.slice(total - dkeyEnd, total - HMAC_LEN - 1)
  if (token[total - dkeyEnd - 1] !== '_') {
    throw new InvalidTokenError('invalid_format', 'Malformed token structure')
  }
  const authEnd = dkeyEnd + 1 + AUTH_SECRET_LEN
  const authSecretB64 = token.slice(total - authEnd, total - dkeyEnd - 1)
  if (token[total - authEnd - 1] !== '_') {
    throw new InvalidTokenError('invalid_format', 'Malformed token structure')
  }

  const prefixPart = token.slice(0, total - suffixLen - 1)
  const parts = prefixPart.split('_')
  if (parts.length !== 5) {
    throw new InvalidTokenError('invalid_format', 'Malformed token structure (prefix)')
  }
  const [prefix, version, idB32, expB36, permsHex] = parts as [string, string, string, string, string]

  if (prefix !== PREFIX) {
    throw new InvalidTokenError('invalid_prefix', "Token must start with 'hrpv_'")
  }
  if (version !== VERSION) {
    throw new InvalidTokenError('unsupported_version', `Unsupported token version: ${version}`)
  }
  if (idB32.length !== ID_B32_LEN) {
    throw new InvalidTokenError('invalid_id_encoding', 'Invalid API key ID encoding')
  }

  const apiKeyId = decodeBase32Uuid(idB32)
  const exp = parseInt(expB36, 36)
  if (Number.isNaN(exp)) {
    throw new InvalidTokenError('invalid_exp_encoding', 'Cannot decode expiration')
  }
  const perms = parseInt(permsHex, 16)
  if (Number.isNaN(perms) || perms < 0 || perms > 0x3f) {
    throw new InvalidTokenError('invalid_perms_value', `Permissions out of range: ${permsHex}`)
  }

  const decryptionKey = base64UrlDecode(dkeyB64)
  if (decryptionKey.length !== 32) {
    throw new InvalidTokenError(
      'invalid_dkey_length',
      `Decryption key must be 32 bytes, got ${decryptionKey.length}`,
    )
  }

  if (exp !== 0 && exp < Math.floor(Date.now() / 1000)) {
    throw new TokenExpiredError()
  }

  return {
    version,
    apiKeyId,
    exp,
    permissions: perms,
    authSecretB64,
    decryptionKey,
    dkeyB64,
    hmacB64,
  }
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const B32_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'

function decodeBase32Uuid(b32: string): string {
  // RFC 4648 lowercase 26 chars → 16 bytes UUID
  const padded = (b32.toUpperCase() + '======').slice(0, 32)
  const bytes = base32Decode(padded)
  if (bytes.length !== 16) {
    throw new InvalidTokenError('invalid_id_encoding', 'Cannot decode API key ID')
  }
  // Format UUID standard 8-4-4-4-12
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`
}

function base32Decode(s: string): Uint8Array {
  const clean = s.replace(/=+$/, '')
  const out: number[] = []
  let buffer = 0
  let bitsLeft = 0
  for (const c of clean) {
    const idx = B32_ALPHABET.indexOf(c)
    if (idx < 0) {
      throw new InvalidTokenError('invalid_id_encoding', `Invalid base32 char: ${c}`)
    }
    buffer = (buffer << 5) | idx
    bitsLeft += 5
    if (bitsLeft >= 8) {
      bitsLeft -= 8
      out.push((buffer >> bitsLeft) & 0xff)
    }
  }
  return new Uint8Array(out)
}

function base64UrlDecode(s: string): Uint8Array {
  // Conversion base64url → base64 standard
  let padded = s.replace(/-/g, '+').replace(/_/g, '/')
  while (padded.length % 4 !== 0) padded += '='
  // atob disponible en Node 18+ et browser
  const binary = atob(padded)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}
