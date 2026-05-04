/**
 * AES-GCM encrypt/decrypt round-trip tests.
 */
import { describe, it, expect } from 'vitest'
import { aesGcmEncrypt, aesGcmDecrypt } from '@/crypto/aes-gcm'

describe('aes-gcm', () => {
  it('encrypts and decrypts a short string round-trip', async () => {
    const key = crypto.getRandomValues(new Uint8Array(32))
    const plaintext = new TextEncoder().encode('hello world')

    const ciphertext = await aesGcmEncrypt(plaintext, key)
    const decrypted = await aesGcmDecrypt(ciphertext, key)

    expect(new TextDecoder().decode(decrypted)).toBe('hello world')
  })

  it('ciphertext includes a 12-byte nonce prefix', async () => {
    const key = crypto.getRandomValues(new Uint8Array(32))
    const plaintext = new TextEncoder().encode('test')

    const ciphertext = await aesGcmEncrypt(plaintext, key)
    // 12 nonce + 4 plaintext + 16 GCM tag = 32 bytes minimum
    expect(ciphertext.length).toBeGreaterThanOrEqual(12 + 4 + 16)
  })

  it('produces different ciphertext each call (random nonce)', async () => {
    const key = crypto.getRandomValues(new Uint8Array(32))
    const plaintext = new TextEncoder().encode('same message')

    const ct1 = await aesGcmEncrypt(plaintext, key)
    const ct2 = await aesGcmEncrypt(plaintext, key)

    // Nonces should differ
    expect(Array.from(ct1.slice(0, 12))).not.toEqual(Array.from(ct2.slice(0, 12)))
  })

  it('throws on wrong key (authentication tag mismatch)', async () => {
    const key1 = crypto.getRandomValues(new Uint8Array(32))
    const key2 = crypto.getRandomValues(new Uint8Array(32))
    const plaintext = new TextEncoder().encode('secret')

    const ciphertext = await aesGcmEncrypt(plaintext, key1)

    await expect(aesGcmDecrypt(ciphertext, key2)).rejects.toThrow()
  })

  it('encrypts and decrypts empty bytes', async () => {
    const key = crypto.getRandomValues(new Uint8Array(32))
    const plaintext = new Uint8Array(0)

    const ciphertext = await aesGcmEncrypt(plaintext, key)
    const decrypted = await aesGcmDecrypt(ciphertext, key)

    expect(decrypted.length).toBe(0)
  })

  it('encrypts and decrypts large binary data', async () => {
    const key = crypto.getRandomValues(new Uint8Array(32))
    const plaintext = crypto.getRandomValues(new Uint8Array(10_000))

    const ciphertext = await aesGcmEncrypt(plaintext, key)
    const decrypted = await aesGcmDecrypt(ciphertext, key)

    expect(Array.from(decrypted)).toEqual(Array.from(plaintext))
  })
})