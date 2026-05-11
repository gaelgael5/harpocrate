/**
 * AES-GCM encryption/decryption using WebCrypto API.
 *
 * Wire format: 12-byte nonce || ciphertext+tag (WebCrypto includes the 16-byte
 * authentication tag in the ciphertext output automatically).
 */

/** Copy Uint8Array to a plain ArrayBuffer, satisfying WebCrypto's BufferSource type. */
function toBuffer(arr: Uint8Array): ArrayBuffer {
  return arr.buffer.slice(
    arr.byteOffset,
    arr.byteOffset + arr.byteLength,
  ) as ArrayBuffer;
}

/**
 * Encrypts plaintext with a 32-byte AES-GCM key.
 * Returns: nonce (12 bytes) || ciphertext+tag
 */
export async function aesGcmEncrypt(
  plaintext: Uint8Array,
  key: Uint8Array,
): Promise<Uint8Array> {
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    toBuffer(key),
    { name: "AES-GCM" },
    false,
    ["encrypt"],
  );
  const nonce = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce },
      cryptoKey,
      toBuffer(plaintext),
    ),
  );
  const result = new Uint8Array(nonce.length + ciphertext.length);
  result.set(nonce, 0);
  result.set(ciphertext, nonce.length);
  return result;
}

/**
 * Decrypts a blob (nonce || ciphertext+tag) with a 32-byte AES-GCM key.
 * Throws DOMException with name 'OperationError' if authentication fails.
 */
export async function aesGcmDecrypt(
  blob: Uint8Array,
  key: Uint8Array,
): Promise<Uint8Array> {
  if (blob.length < 12 + 16) {
    throw new Error("AES-GCM blob too short (minimum 28 bytes)");
  }
  const cryptoKey = await crypto.subtle.importKey(
    "raw",
    toBuffer(key),
    { name: "AES-GCM" },
    false,
    ["decrypt"],
  );
  const nonce = blob.slice(0, 12);
  const ciphertext = blob.slice(12);
  return new Uint8Array(
    await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: nonce },
      cryptoKey,
      toBuffer(ciphertext),
    ),
  );
}
