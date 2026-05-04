/**
 * Argon2id KDF tests using hash-wasm.
 */
import { describe, it, expect } from 'vitest'
import { deriveKey, deriveKeyFromSeed } from '@/crypto/argon2'

describe('argon2 KDF', () => {
  const testParams = {
    memory_kb: 1024, // Low values for fast tests
    iterations: 1,
    parallelism: 1,
  }

  it('derives a 32-byte key from a passphrase', async () => {
    const passphrase = 'my-test-passphrase'
    const salt = crypto.getRandomValues(new Uint8Array(16))

    const key = await deriveKey(passphrase, salt, testParams)

    expect(key).toBeInstanceOf(Uint8Array)
    expect(key.length).toBe(32)
  })

  it('is deterministic — same input gives same output', async () => {
    const passphrase = 'deterministic-test'
    const salt = new Uint8Array(16).fill(0x42)

    const k1 = await deriveKey(passphrase, salt, testParams)
    const k2 = await deriveKey(passphrase, salt, testParams)

    expect(Array.from(k1)).toEqual(Array.from(k2))
  })

  it('different salt produces different key', async () => {
    const passphrase = 'same-passphrase'
    const salt1 = new Uint8Array(16).fill(0x11)
    const salt2 = new Uint8Array(16).fill(0x22)

    const k1 = await deriveKey(passphrase, salt1, testParams)
    const k2 = await deriveKey(passphrase, salt2, testParams)

    expect(Array.from(k1)).not.toEqual(Array.from(k2))
  })

  it('different passphrase produces different key', async () => {
    const salt = new Uint8Array(16).fill(0xAA)

    const k1 = await deriveKey('passphrase-one', salt, testParams)
    const k2 = await deriveKey('passphrase-two', salt, testParams)

    expect(Array.from(k1)).not.toEqual(Array.from(k2))
  })

  it('deriveKeyFromSeed accepts Uint8Array input', async () => {
    const seed = crypto.getRandomValues(new Uint8Array(32))
    const salt = crypto.getRandomValues(new Uint8Array(16))

    const key = await deriveKeyFromSeed(seed, salt, testParams)

    expect(key).toBeInstanceOf(Uint8Array)
    expect(key.length).toBe(32)
  })
})