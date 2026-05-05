import { describe, expect, it } from 'vitest'

import { aesGcmDecrypt, aesGcmEncrypt } from '../src/crypto.js'
import { VaultDecryptionError } from '../src/errors.js'

const KEY_32 = new Uint8Array(32).fill(7)

describe('AES-GCM', () => {
  it('round-trips encrypt then decrypt', async () => {
    const plain = new TextEncoder().encode('hello vault')
    const blob = await aesGcmEncrypt(plain, KEY_32)
    const out = await aesGcmDecrypt(blob, KEY_32)
    expect(new TextDecoder().decode(out)).toBe('hello vault')
  })

  it('rejects wrong key on decrypt', async () => {
    const blob = await aesGcmEncrypt(new Uint8Array([1, 2, 3]), KEY_32)
    const wrong = new Uint8Array(32).fill(8)
    await expect(aesGcmDecrypt(blob, wrong)).rejects.toThrowError(
      VaultDecryptionError,
    )
  })

  it('rejects short key', async () => {
    await expect(
      aesGcmEncrypt(new Uint8Array([1]), new Uint8Array(16)),
    ).rejects.toThrowError(VaultDecryptionError)
  })

  it('rejects short blob', async () => {
    await expect(aesGcmDecrypt(new Uint8Array(5), KEY_32)).rejects.toThrowError(
      VaultDecryptionError,
    )
  })

  it('blob format is nonce(12) + ciphertext + tag(16)', async () => {
    const blob = await aesGcmEncrypt(new Uint8Array([0xaa]), KEY_32)
    expect(blob.length).toBe(12 + 1 + 16) // 29
  })
})
