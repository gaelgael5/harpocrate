/**
 * Client haut-niveau Harpocrate Vault — JavaScript pur.
 *
 * Le SDK déchiffre côté client — le serveur ne voit jamais les valeurs en clair.
 * Supporte les secrets path-style via résolution by-id (pattern aligné sur SDK
 * Python 0.6.0, Rust 0.2.0, TypeScript 0.2.0, C# 0.2.0).
 */
import { aesGcmDecrypt, aesGcmEncrypt, base64ToBytes, bytesToBase64 } from './crypto.js';
import {
  SecretNotFoundError,
  VaultDecryptionError,
  VaultHttpError,
} from './errors.js';
import { parseToken } from './token.js';

export class VaultClient {
  constructor(parsed, walletId, baseUrl, fetcher, authHeader) {
    this.parsed = parsed;
    this.walletId = walletId;
    this.baseUrl = baseUrl.replace(/\/+$/, '');
    this.fetcher = fetcher;
    this.authHeader = authHeader;
    this.walletKey = null;
    this.walletKeyPromise = null;
  }

  static async create({ token, baseUrl, fetch: customFetch }) {
    const parsed = parseToken(token);
    const fetcher = customFetch ?? globalThis.fetch.bind(globalThis);
    const authHeader = `Bearer ${token}`;
    const trimmedBase = baseUrl.replace(/\/+$/, '');
    const widResp = await getJson(
      fetcher,
      authHeader,
      `${trimmedBase}/v1/api-keys/${parsed.apiKeyId}/wallet-id`,
    );
    return new VaultClient(parsed, widResp.wallet_id, trimmedBase, fetcher, authHeader);
  }

  whoami() {
    return {
      apiKeyId: this.parsed.apiKeyId,
      walletId: this.walletId,
      permissions: this.parsed.permissions,
      exp: this.parsed.exp,
    };
  }

  async listSecrets() {
    return getJson(
      this.fetcher,
      this.authHeader,
      `${this.baseUrl}/v1/wallets/${this.walletId}/secrets`,
    );
  }

  async getSecret(name) {
    const url = await this.pathForOp(name);
    const resp = await getJson(this.fetcher, this.authHeader, url);
    const wk = await this.getWalletKey();
    const enc = base64ToBytes(resp.encrypted_value);
    const plain = await aesGcmDecrypt(enc, wk);
    return new TextDecoder().decode(plain);
  }

  async createSecret(name, value) {
    const wk = await this.getWalletKey();
    const enc = await aesGcmEncrypt(new TextEncoder().encode(value), wk);
    const body = { name, encrypted_value: bytesToBase64(enc) };
    const resp = await postJson(
      this.fetcher,
      this.authHeader,
      `${this.baseUrl}/v1/wallets/${this.walletId}/secrets`,
      body,
    );
    return resp.secret_id;
  }

  async putSecret(name, value) {
    const wk = await this.getWalletKey();
    const enc = await aesGcmEncrypt(new TextEncoder().encode(value), wk);
    const body = { encrypted_value: bytesToBase64(enc) };
    const url = await this.pathForOp(name);
    const resp = await putJson(this.fetcher, this.authHeader, url, body);
    return resp.generation_version;
  }

  async deleteSecret(name) {
    const url = await this.pathForOp(name);
    const r = await this.fetcher(url, {
      method: 'DELETE',
      headers: { authorization: this.authHeader },
    });
    if (!r.ok) {
      const body = await r.text().catch(() => '');
      if (r.status === 404) throw new SecretNotFoundError(name);
      throw new VaultHttpError(r.status, body);
    }
  }

  // ─── Internals ────────────────────────────────────────────────────────────

  async getWalletKey() {
    if (this.walletKey) return this.walletKey;
    if (this.walletKeyPromise) return this.walletKeyPromise;
    this.walletKeyPromise = (async () => {
      const grant = await getJson(
        this.fetcher,
        this.authHeader,
        `${this.baseUrl}/v1/wallets/${this.walletId}/my-api-key-grant`,
      );
      const enc = base64ToBytes(grant.encrypted_wallet_key);
      const wk = await aesGcmDecrypt(enc, this.parsed.decryptionKey);
      if (wk.length !== 32) {
        throw new VaultDecryptionError('wallet_key not 32 bytes');
      }
      this.walletKey = wk;
      return wk;
    })();
    try {
      return await this.walletKeyPromise;
    } finally {
      this.walletKeyPromise = null;
    }
  }

  secretUrlByName(name) {
    const normalized = name.includes('/') && !name.startsWith('/') ? `/${name}` : name;
    return `${this.baseUrl}/v1/wallets/${this.walletId}/secrets/${encodeURIComponent(normalized)}`;
  }

  secretUrlById(sid) {
    return `${this.baseUrl}/v1/wallets/${this.walletId}/secrets/by-id/${sid}`;
  }

  /**
   * Si `name` contient `/`, résout l'UUID via GET /secrets?path=<parent>,
   * puis filtre par nom. Retourne null pour les noms plats.
   *
   * Évite la dépendance fragile au comportement des reverse proxies sur
   * les `/` URL-encodés (%2F).
   */
  async resolveIdIfPathstyle(name) {
    if (!name.includes('/')) return null;
    const normalized = name.startsWith('/') ? name : `/${name}`;
    const lastSlash = normalized.lastIndexOf('/');
    const parentPath = lastSlash === 0 ? '/' : `${normalized.slice(0, lastSlash)}/`;
    const listUrl = `${this.baseUrl}/v1/wallets/${this.walletId}/secrets?path=${encodeURIComponent(parentPath)}`;
    const listing = await getJson(this.fetcher, this.authHeader, listUrl);
    const match = listing.secrets?.find((s) => s.name === normalized);
    if (!match) throw new SecretNotFoundError(name);
    return match.id;
  }

  async pathForOp(name) {
    const sid = await this.resolveIdIfPathstyle(name);
    return sid !== null ? this.secretUrlById(sid) : this.secretUrlByName(name);
  }
}

// ─── HTTP helpers ─────────────────────────────────────────────────────────────

async function getJson(fetcher, authHeader, url) {
  const r = await fetcher(url, { headers: { authorization: authHeader } });
  return readBodyOrThrow(r, url);
}

async function postJson(fetcher, authHeader, url, body) {
  const r = await fetcher(url, {
    method: 'POST',
    headers: { authorization: authHeader, 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return readBodyOrThrow(r, url);
}

async function putJson(fetcher, authHeader, url, body) {
  const r = await fetcher(url, {
    method: 'PUT',
    headers: { authorization: authHeader, 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  return readBodyOrThrow(r, url);
}

async function readBodyOrThrow(r, ctx) {
  if (r.status === 404) {
    throw new SecretNotFoundError(ctx);
  }
  if (!r.ok) {
    const body = await r.text().catch(() => '');
    throw new VaultHttpError(r.status, body);
  }
  if (r.status === 204) return null;
  return r.json();
}
