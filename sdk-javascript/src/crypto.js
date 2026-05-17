/**
 * AES-256-GCM via Web Crypto API — format `nonce(12) || ciphertext || tag(16)`.
 *
 * Compatible Node 18+ (subtle crypto) et tous browsers modernes.
 */
import { VaultDecryptionError } from './errors.js';

const NONCE_LEN = 12;
const TAG_LEN = 16;

function getSubtle() {
  if (typeof globalThis.crypto?.subtle === 'undefined') {
    throw new VaultDecryptionError('Web Crypto API (crypto.subtle) is not available');
  }
  return globalThis.crypto.subtle;
}

async function importAesKey(key) {
  if (key.length !== 32) {
    throw new VaultDecryptionError(`key must be 32 bytes, got ${key.length}`);
  }
  return getSubtle().importKey('raw', key, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
}

export async function aesGcmEncrypt(plaintext, key) {
  const cryptoKey = await importAesKey(key);
  const nonce = globalThis.crypto.getRandomValues(new Uint8Array(NONCE_LEN));
  const ciphertext = await getSubtle().encrypt(
    { name: 'AES-GCM', iv: nonce, tagLength: TAG_LEN * 8 },
    cryptoKey,
    plaintext,
  );
  const cipherBytes = new Uint8Array(ciphertext);
  const out = new Uint8Array(NONCE_LEN + cipherBytes.length);
  out.set(nonce, 0);
  out.set(cipherBytes, NONCE_LEN);
  return out;
}

export async function aesGcmDecrypt(blob, key) {
  if (blob.length < NONCE_LEN + TAG_LEN) {
    throw new VaultDecryptionError(`blob too short: ${blob.length} bytes`);
  }
  const cryptoKey = await importAesKey(key);
  const nonce = blob.slice(0, NONCE_LEN);
  const ciphertext = blob.slice(NONCE_LEN);
  try {
    const plain = await getSubtle().decrypt(
      { name: 'AES-GCM', iv: nonce, tagLength: TAG_LEN * 8 },
      cryptoKey,
      ciphertext,
    );
    return new Uint8Array(plain);
  } catch (_err) {
    throw new VaultDecryptionError('AES-GCM decryption failed: invalid tag or wrong key');
  }
}

// ─── Helpers base64 (utiles côté client) ───────────────────────────────────

export function base64ToBytes(s) {
  const binary = atob(s);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export function bytesToBase64(bytes) {
  let binary = '';
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}
