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

// Default parameters matching backend defaults
export const DEFAULT_KDF_PARAMS: KdfParams = {
  memory_kb: 65536,
  iterations: 3,
  parallelism: 1,
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
