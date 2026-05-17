/**
 * Client haut-niveau Harpocrate Vault.
 *
 * Le SDK déchiffre côté client — le serveur ne voit jamais les valeurs en clair.
 */
import { aesGcmDecrypt, aesGcmEncrypt } from './crypto.js'
import {
  HarpocrateError,
  SecretNotFoundError,
  VaultDecryptionError,
  VaultHttpError,
} from './errors.js'
import { type ParsedToken, parseToken } from './token.js'

export interface SecretInfo {
  id: string
  name: string
  description?: string | null
  tags?: string[]
  is_placeholder?: boolean
  generation_version?: number
}

export interface SecretListResponse {
  secrets: SecretInfo[]
  next_cursor?: string | null
}

export interface WalletInfo {
  id: string
  name: string
  description?: string | null
}

export interface ApiKeyInfo {
  apiKeyId: string
  walletId: string
  permissions: number
  exp: number
}

export interface VaultClientOptions {
  /** Token hrpv_*. */
  token: string
  /** URL de base (sans trailing slash). */
  baseUrl: string
  /** Optionnel : fetch custom (utile pour tests/proxy). */
  fetch?: typeof globalThis.fetch
}

export class VaultClient {
  readonly walletId: string
  private readonly parsed: ParsedToken
  private readonly baseUrl: string
  private readonly fetcher: typeof globalThis.fetch
  private readonly authHeader: string
  private walletKey: Uint8Array | null = null
  private walletKeyPromise: Promise<Uint8Array> | null = null

  private constructor(
    parsed: ParsedToken,
    walletId: string,
    baseUrl: string,
    fetcher: typeof globalThis.fetch,
    authHeader: string,
  ) {
    this.parsed = parsed
    this.walletId = walletId
    this.baseUrl = baseUrl.replace(/\/+$/, '')
    this.fetcher = fetcher
    this.authHeader = authHeader
  }

  static async create(options: VaultClientOptions): Promise<VaultClient> {
    const parsed = parseToken(options.token)
    const fetcher = options.fetch ?? globalThis.fetch.bind(globalThis)
    const authHeader = `Bearer ${options.token}`
    const baseUrl = options.baseUrl.replace(/\/+$/, '')

    const widResp = await getJson<{ wallet_id: string }>(
      fetcher,
      authHeader,
      `${baseUrl}/v1/api-keys/${parsed.apiKeyId}/wallet-id`,
    )
    return new VaultClient(parsed, widResp.wallet_id, baseUrl, fetcher, authHeader)
  }

  whoami(): ApiKeyInfo {
    return {
      apiKeyId: this.parsed.apiKeyId,
      walletId: this.walletId,
      permissions: this.parsed.permissions,
      exp: this.parsed.exp,
    }
  }

  async walletInfo(): Promise<WalletInfo> {
    return getJson<WalletInfo>(
      this.fetcher,
      this.authHeader,
      `${this.baseUrl}/v1/wallets/${this.walletId}`,
    )
  }

  async listSecrets(): Promise<SecretListResponse> {
    return getJson<SecretListResponse>(
      this.fetcher,
      this.authHeader,
      `${this.baseUrl}/v1/wallets/${this.walletId}/secrets`,
    )
  }

  async getSecret(name: string): Promise<string> {
    const url = await this.pathForOp(name)
    const resp = await getJson<{ encrypted_value: string }>(
      this.fetcher,
      this.authHeader,
      url,
    )
    const wk = await this.getWalletKey()
    const enc = base64ToBytes(resp.encrypted_value)
    const plain = await aesGcmDecrypt(enc, wk)
    return new TextDecoder().decode(plain)
  }

  async createSecret(name: string, value: string): Promise<string> {
    const wk = await this.getWalletKey()
    const enc = await aesGcmEncrypt(new TextEncoder().encode(value), wk)
    const body = { name, encrypted_value: bytesToBase64(enc) }
    const resp = await postJson<{ secret_id: string }>(
      this.fetcher,
      this.authHeader,
      `${this.baseUrl}/v1/wallets/${this.walletId}/secrets`,
      body,
    )
    return resp.secret_id
  }

  async putSecret(name: string, value: string): Promise<number> {
    const wk = await this.getWalletKey()
    const enc = await aesGcmEncrypt(new TextEncoder().encode(value), wk)
    const body = { encrypted_value: bytesToBase64(enc) }
    const url = await this.pathForOp(name)
    const resp = await putJson<{ generation_version: number }>(
      this.fetcher,
      this.authHeader,
      url,
      body,
    )
    return resp.generation_version
  }

  async deleteSecret(name: string): Promise<void> {
    const url = await this.pathForOp(name)
    const r = await this.fetcher(url, {
      method: 'DELETE',
      headers: { authorization: this.authHeader },
    })
    if (!r.ok) {
      const body = await r.text().catch(() => '')
      if (r.status === 404) throw new SecretNotFoundError(name)
      throw new VaultHttpError(r.status, body)
    }
  }

  // ─── Internals ────────────────────────────────────────────────────────────

  private async getWalletKey(): Promise<Uint8Array> {
    if (this.walletKey) return this.walletKey
    if (this.walletKeyPromise) return this.walletKeyPromise
    this.walletKeyPromise = (async () => {
      const grant = await getJson<{ encrypted_wallet_key: string }>(
        this.fetcher,
        this.authHeader,
        `${this.baseUrl}/v1/wallets/${this.walletId}/my-api-key-grant`,
      )
      const enc = base64ToBytes(grant.encrypted_wallet_key)
      const wk = await aesGcmDecrypt(enc, this.parsed.decryptionKey)
      if (wk.length !== 32) {
        throw new VaultDecryptionError('wallet_key not 32 bytes')
      }
      this.walletKey = wk
      return wk
    })()
    try {
      return await this.walletKeyPromise
    } finally {
      this.walletKeyPromise = null
    }
  }

  private secretUrlByName(name: string): string {
    const normalized = name.includes('/') && !name.startsWith('/') ? `/${name}` : name
    return `${this.baseUrl}/v1/wallets/${this.walletId}/secrets/${encodeURIComponent(normalized)}`
  }

  private secretUrlById(sid: string): string {
    return `${this.baseUrl}/v1/wallets/${this.walletId}/secrets/by-id/${sid}`
  }

  /**
   * Si `name` contient `/` (path-style), résout l'UUID via
   * GET /v1/wallets/<wid>/secrets?path=<parent>, puis filtre par nom.
   * Retourne null pour les noms plats (le caller utilisera la route name-based).
   *
   * Évite la dépendance fragile au comportement des reverse proxies vis-à-vis
   * des `/` URL-encodés (`%2F`) — pattern aligné sur SDK Python 0.6.0.
   */
  private async resolveIdIfPathstyle(name: string): Promise<string | null> {
    if (!name.includes('/')) return null
    const normalized = name.startsWith('/') ? name : `/${name}`
    const lastSlash = normalized.lastIndexOf('/')
    const parentPath = lastSlash === 0 ? '/' : `${normalized.slice(0, lastSlash)}/`
    const listUrl = `${this.baseUrl}/v1/wallets/${this.walletId}/secrets?path=${encodeURIComponent(parentPath)}`
    const listing = await getJson<SecretListResponse>(this.fetcher, this.authHeader, listUrl)
    const match = listing.secrets?.find((s) => s.name === normalized)
    if (!match) throw new SecretNotFoundError(name)
    return match.id
  }

  /**
   * Retourne l'URL d'opération unitaire :
   * `/by-id/<sid>` pour les noms path-style, `/<encoded-name>` pour les noms plats.
   */
  private async pathForOp(name: string): Promise<string> {
    const sid = await this.resolveIdIfPathstyle(name)
    return sid !== null ? this.secretUrlById(sid) : this.secretUrlByName(name)
  }
}

// ─── HTTP helpers ─────────────────────────────────────────────────────────────

async function getJson<T>(
  fetcher: typeof globalThis.fetch,
  authHeader: string,
  url: string,
): Promise<T> {
  const r = await fetcher(url, { headers: { authorization: authHeader } })
  await ensureSuccess(r, url)
  return (await r.json()) as T
}

async function postJson<T>(
  fetcher: typeof globalThis.fetch,
  authHeader: string,
  url: string,
  body: unknown,
): Promise<T> {
  const r = await fetcher(url, {
    method: 'POST',
    headers: {
      authorization: authHeader,
      'content-type': 'application/json',
    },
    body: JSON.stringify(body),
  })
  await ensureSuccess(r, url)
  return (await r.json()) as T
}

async function putJson<T>(
  fetcher: typeof globalThis.fetch,
  authHeader: string,
  url: string,
  body: unknown,
): Promise<T> {
  const r = await fetcher(url, {
    method: 'PUT',
    headers: {
      authorization: authHeader,
      'content-type': 'application/json',
    },
    body: JSON.stringify(body),
  })
  await ensureSuccess(r, url)
  return (await r.json()) as T
}

async function ensureSuccess(r: Response, ctx: string): Promise<void> {
  if (r.ok) return
  const body = await r.text().catch(() => '')
  if (r.status === 404) {
    throw new SecretNotFoundError(ctx)
  }
  throw new VaultHttpError(r.status, body)
}

function base64ToBytes(b64: string): Uint8Array {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  for (const b of bytes) binary += String.fromCharCode(b)
  return btoa(binary)
}

// Re-exports pour usage par les types pubs
export { HarpocrateError }
