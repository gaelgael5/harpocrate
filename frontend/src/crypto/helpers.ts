/**
 * Miscellaneous crypto/encoding helpers.
 */

/**
 * Encodes a Uint8Array to a standard base64 string (no line breaks).
 */
export function toBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunkSize = 8192
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.slice(i, i + chunkSize))
  }
  return btoa(binary)
}

/**
 * Decodes a standard base64 string to Uint8Array.
 */
export function fromBase64(b64: string): Uint8Array {
  const binary = atob(b64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i)
  }
  return bytes
}

/**
 * Returns cryptographically random bytes.
 */
export function randomBytes(length: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(length))
}

/**
 * Encodes a UTF-8 string to bytes.
 */
export function textToBytes(text: string): Uint8Array {
  return new TextEncoder().encode(text)
}

/**
 * Decodes bytes to a UTF-8 string.
 */
export function bytesToText(bytes: Uint8Array): string {
  return new TextDecoder().decode(bytes)
}

/**
 * Constant-time comparison of two Uint8Arrays to prevent timing attacks.
 */
export function timingSafeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false
  let diff = 0
  for (let i = 0; i < a.length; i++) {
    diff |= (a[i]! ^ b[i]!)
  }
  return diff === 0
}
