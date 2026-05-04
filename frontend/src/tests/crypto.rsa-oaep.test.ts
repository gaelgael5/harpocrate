/**
 * RSA-OAEP keypair generation and encrypt/decrypt tests.
 */
import { describe, it, expect } from 'vitest'
import { generateRsaKeypair, rsaOaepEncrypt, rsaOaepDecrypt } from '@/crypto/rsa-oaep'

describe('rsa-oaep', () => {
  it('generates a 2048-bit keypair with non-empty SPKI/PKCS8 bytes', async () => {
    const { publicKey, privateKey } = await generateRsaKeypair(2048)
    expect(publicKey.length).toBeGreaterThan(100)
    expect(privateKey.length).toBeGreaterThan(100)
  }, 15_000)

  it('encrypts and decrypts a 32-byte key round-trip', async () => {
    const { publicKey, privateKey } = await generateRsaKeypair(2048)
    const secret = crypto.getRandomValues(new Uint8Array(32))

    const ciphertext = await rsaOaepEncrypt(secret, publicKey)
    const decrypted = await rsaOaepDecrypt(ciphertext, privateKey)

    expect(Array.from(decrypted)).toEqual(Array.from(secret))
  }, 15_000)

  it('produces different ciphertext each call (OAEP random padding)', async () => {
    const { publicKey } = await generateRsaKeypair(2048)
    const secret = crypto.getRandomValues(new Uint8Array(32))

    const ct1 = await rsaOaepEncrypt(secret, publicKey)
    const ct2 = await rsaOaepEncrypt(secret, publicKey)

    // OAEP padding is randomized
    expect(Array.from(ct1)).not.toEqual(Array.from(ct2))
  }, 15_000)

  it('fails to decrypt with wrong private key', async () => {
    const kp1 = await generateRsaKeypair(2048)
    const kp2 = await generateRsaKeypair(2048)
    const secret = crypto.getRandomValues(new Uint8Array(32))

    const ciphertext = await rsaOaepEncrypt(secret, kp1.publicKey)

    await expect(rsaOaepDecrypt(ciphertext, kp2.privateKey)).rejects.toThrow()
  }, 30_000)
})