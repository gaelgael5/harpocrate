/**
 * Argon2id KDF wrapper using hash-wasm.
 * hash-wasm is preferred over argon2-browser due to better Vite compatibility.
 */
import { argon2id } from 'hash-wasm'

export interface KdfParams {
  memory_kb: number
  iterations: number
  parallelism: number
}

// Default parameters matching backend floors (OVERVIEW.md §3) :
// memory_kb >= 65536, iterations >= 3, parallelism >= 4.
// Le serveur rejette toute config en dessous des floors (400 kdf_floor_violation).
export const DEFAULT_KDF_PARAMS: KdfParams = {
  memory_kb: 65536,
  iterations: 3,
  parallelism: 4,
}

/**
 * Derives a 32-byte key from a passphrase and salt using Argon2id.
 * This mirrors the Python backend's argon2.low_level.hash_secret_raw.
 */
export async function deriveKey(
  passphrase: string,
  salt: Uint8Array,
  params: KdfParams = DEFAULT_KDF_PARAMS,
): Promise<Uint8Array> {
  const result = await argon2id({
    password: passphrase,
    salt,
    parallelism: params.parallelism,
    iterations: params.iterations,
    memorySize: params.memory_kb,
    hashLength: 32,
    outputType: 'binary',
  })
  return result as Uint8Array
}

/**
 * Derives a 32-byte key from a binary seed and salt using Argon2id.
 * Used for the recovery key derivation.
 */
export async function deriveKeyFromSeed(
  seed: Uint8Array,
  salt: Uint8Array,
  params: KdfParams = DEFAULT_KDF_PARAMS,
): Promise<Uint8Array> {
  const result = await argon2id({
    password: seed,
    salt,
    parallelism: params.parallelism,
    iterations: params.iterations,
    memorySize: params.memory_kb,
    hashLength: 32,
    outputType: 'binary',
  })
  return result as Uint8Array
}

/**
 * Computes an Argon2id PHC-format hash of a base64url secret string.
 *
 * The backend stores auth_hash as a PHC string and verifies with
 * argon2-cffi's PasswordHasher.verify(phc_string, secret_b64url.encode()).
 * The password must be the base64url string (not the raw bytes) so that
 * the server can re-verify using auth_secret_b64 from the token.
 */
export async function hashAuthSecret(
  secretB64Url: string,
  salt: Uint8Array,
  params: KdfParams = DEFAULT_KDF_PARAMS,
): Promise<string> {
  const result = await argon2id({
    password: secretB64Url,
    salt,
    parallelism: params.parallelism,
    iterations: params.iterations,
    memorySize: params.memory_kb,
    hashLength: 32,
    outputType: 'encoded',
  })
  return result as string
}
