/**
 * AES-256-GCM via Web Crypto API — format `nonce(12) || ciphertext || tag(16)`.
 *
 * Compatible Node 18+ (subtle crypto) et tous browsers modernes.
 */
import { VaultDecryptionError } from './errors.js'

const NONCE_LEN = 12
const TAG_LEN = 16

function getSubtle(): SubtleCrypto {
  if (typeof globalThis.crypto?.subtle === 'undefined') {
    throw new VaultDecryptionError('Web Crypto API (crypto.subtle) is not available')
  }
  return globalThis.crypto.subtle
}

async function importAesKey(key: Uint8Array): Promise<CryptoKey> {
  if (key.length !== 32) {
    throw new VaultDecryptionError(`key must be 32 bytes, got ${key.length}`)
  }
  return getSubtle().importKey(
    'raw',
    key as unknown as ArrayBuffer,
    { name: 'AES-GCM' },
    false,
    ['encrypt', 'decrypt'],
  )
}

export async function aesGcmEncrypt(plaintext: Uint8Array, key: Uint8Array): Promise<Uint8Array> {
  const cryptoKey = await importAesKey(key)
  const nonce = globalThis.crypto.getRandomValues(new Uint8Array(NONCE_LEN))
  const ciphertext = await getSubtle().encrypt(
    { name: 'AES-GCM', iv: nonce, tagLength: TAG_LEN * 8 },
    cryptoKey,
    plaintext as unknown as ArrayBuffer,
  )
  const cipherBytes = new Uint8Array(ciphertext)
  const out = new Uint8Array(NONCE_LEN + cipherBytes.length)
  out.set(nonce, 0)
  out.set(cipherBytes, NONCE_LEN)
  return out
}

export async function aesGcmDecrypt(blob: Uint8Array, key: Uint8Array): Promise<Uint8Array> {
  if (blob.length < NONCE_LEN + TAG_LEN) {
    throw new VaultDecryptionError(`blob too short: ${blob.length} bytes`)
  }
  const cryptoKey = await importAesKey(key)
  const nonce = blob.slice(0, NONCE_LEN)
  const ciphertext = blob.slice(NONCE_LEN)
  try {
    const plain = await getSubtle().decrypt(
      { name: 'AES-GCM', iv: nonce, tagLength: TAG_LEN * 8 },
      cryptoKey,
      ciphertext as unknown as ArrayBuffer,
    )
    return new Uint8Array(plain)
  } catch (err) {
    throw new VaultDecryptionError(
      'AES-GCM decryption failed: invalid tag or wrong key',
    )
  }
}
