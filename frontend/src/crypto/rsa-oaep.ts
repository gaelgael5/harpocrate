/**
 * RSA-OAEP key generation, encryption, and decryption using WebCrypto.
 *
 * Key format:
 *   - Public key: SPKI (DER-encoded)  → compatible with Python cryptography lib
 *   - Private key: PKCS8 (DER-encoded) → compatible with Python cryptography lib
 */

/** Copy Uint8Array to a plain ArrayBuffer, satisfying WebCrypto's BufferSource type. */
function toBuffer(arr: Uint8Array): ArrayBuffer {
  return arr.buffer.slice(arr.byteOffset, arr.byteOffset + arr.byteLength) as ArrayBuffer
}

export interface RsaKeypairBytes {
  publicKey: Uint8Array
  privateKey: Uint8Array
}

/**
 * Generates an RSA-OAEP keypair.
 * Returns DER-encoded SPKI (public) and PKCS8 (private) bytes.
 */
export async function generateRsaKeypair(
  keySize: 2048 | 4096 = 2048,
): Promise<RsaKeypairBytes> {
  const pair = await crypto.subtle.generateKey(
    {
      name: 'RSA-OAEP',
      modulusLength: keySize,
      publicExponent: new Uint8Array([1, 0, 1]),
      hash: 'SHA-256',
    },
    true,
    ['encrypt', 'decrypt'],
  )
  const pub = new Uint8Array(
    await crypto.subtle.exportKey('spki', pair.publicKey),
  )
  const priv = new Uint8Array(
    await crypto.subtle.exportKey('pkcs8', pair.privateKey),
  )
  return { publicKey: pub, privateKey: priv }
}

/**
 * Encrypts plaintext with an RSA-OAEP public key (SPKI DER format).
 */
export async function rsaOaepEncrypt(
  plaintext: Uint8Array,
  publicKeyDer: Uint8Array,
): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    'spki',
    toBuffer(publicKeyDer),
    { name: 'RSA-OAEP', hash: 'SHA-256' },
    false,
    ['encrypt'],
  )
  return new Uint8Array(
    await crypto.subtle.encrypt(
      { name: 'RSA-OAEP' },
      key,
      toBuffer(plaintext),
    ),
  )
}

/**
 * Decrypts ciphertext with an RSA-OAEP private key (PKCS8 DER format).
 */
export async function rsaOaepDecrypt(
  ciphertext: Uint8Array,
  privateKeyDer: Uint8Array,
): Promise<Uint8Array> {
  const key = await crypto.subtle.importKey(
    'pkcs8',
    toBuffer(privateKeyDer),
    { name: 'RSA-OAEP', hash: 'SHA-256' },
    false,
    ['decrypt'],
  )
  return new Uint8Array(
    await crypto.subtle.decrypt(
      { name: 'RSA-OAEP' },
      key,
      toBuffer(ciphertext),
    ),
  )
}
