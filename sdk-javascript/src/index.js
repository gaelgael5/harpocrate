/**
 * Harpocrate SDK JavaScript — exports publics.
 */
export { VaultClient } from './client.js';
export { parseToken } from './token.js';
export { aesGcmEncrypt, aesGcmDecrypt, base64ToBytes, bytesToBase64 } from './crypto.js';
export {
  HarpocrateError,
  InvalidTokenError,
  TokenExpiredError,
  SecretNotFoundError,
  VaultHttpError,
  VaultDecryptionError,
} from './errors.js';
