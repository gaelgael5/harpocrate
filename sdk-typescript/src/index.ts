/**
 * Harpocrate SDK — client TypeScript zero-knowledge pour Vault.
 */
export { VaultClient } from './client.js'
export type {
  ApiKeyInfo,
  SecretInfo,
  SecretListResponse,
  VaultClientOptions,
  WalletInfo,
} from './client.js'
export { aesGcmDecrypt, aesGcmEncrypt } from './crypto.js'
export {
  HarpocrateError,
  InvalidTokenError,
  SecretNotFoundError,
  TokenExpiredError,
  VaultDecryptionError,
  VaultHttpError,
} from './errors.js'
export { type ParsedToken, parseToken } from './token.js'
