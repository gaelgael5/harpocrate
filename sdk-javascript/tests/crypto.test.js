import { describe, it, expect } from 'vitest';

import { aesGcmDecrypt, aesGcmEncrypt } from '../src/crypto.js';
import { VaultDecryptionError } from '../src/errors.js';

describe('AES-GCM', () => {
  it('round-trip encrypt then decrypt', async () => {
    const key = new Uint8Array(32).fill(42);
    const plain = new TextEncoder().encode('hello vault');
    const blob = await aesGcmEncrypt(plain, key);
    const decrypted = await aesGcmDecrypt(blob, key);
    expect(new TextDecoder().decode(decrypted)).toBe('hello vault');
  });

  it('rejects wrong key on decrypt', async () => {
    const blob = await aesGcmEncrypt(new TextEncoder().encode('x'), new Uint8Array(32).fill(1));
    await expect(aesGcmDecrypt(blob, new Uint8Array(32).fill(2))).rejects.toBeInstanceOf(
      VaultDecryptionError,
    );
  });

  it('rejects short key on encrypt', async () => {
    await expect(aesGcmEncrypt(new Uint8Array(1), new Uint8Array(16))).rejects.toBeInstanceOf(
      VaultDecryptionError,
    );
  });

  it('rejects short blob on decrypt', async () => {
    await expect(aesGcmDecrypt(new Uint8Array(5), new Uint8Array(32))).rejects.toBeInstanceOf(
      VaultDecryptionError,
    );
  });
});
