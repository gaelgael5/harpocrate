/**
 * BIP-39 mnemonic encoding for a 32-byte recovery seed.
 *
 * A 32-byte seed = 256 bits of entropy.
 * BIP-39 with 256-bit entropy produces 24 words.
 * Checksum = SHA-256(entropy)[0:8 bits] → total bits = 264, 264/11 = 24 words.
 *
 * We embed the English wordlist (2048 words) at build time.
 */

import { WORDLIST } from './bip39-wordlist'

/**
 * Encodes 32 random bytes into a 24-word BIP-39 mnemonic.
 */
export async function encodeBip39(seed: Uint8Array): Promise<string[]> {
  if (seed.length !== 32) {
    throw new Error(`BIP-39 seed must be 32 bytes, got ${seed.length}`)
  }

  // Compute SHA-256 checksum
  // Copy to ArrayBuffer to satisfy TypeScript's strict WebCrypto types
  const seedBuf = seed.buffer.slice(seed.byteOffset, seed.byteOffset + seed.byteLength) as ArrayBuffer
  const hashBuf = await crypto.subtle.digest('SHA-256', seedBuf)
  const hash = new Uint8Array(hashBuf)
  const checkByte = hash[0]! // 8-bit checksum (first byte)

  // Concatenate entropy + checksum bits: 256 + 8 = 264 bits = 24 × 11
  const bits: number[] = []
  for (const byte of seed) {
    for (let i = 7; i >= 0; i--) {
      bits.push((byte >> i) & 1)
    }
  }
  // Add 8 checksum bits
  for (let i = 7; i >= 0; i--) {
    bits.push((checkByte >> i) & 1)
  }

  // Split into 24 groups of 11 bits
  const words: string[] = []
  for (let w = 0; w < 24; w++) {
    let idx = 0
    for (let b = 0; b < 11; b++) {
      idx = (idx << 1) | (bits[w * 11 + b]! ?? 0)
    }
    const word = WORDLIST[idx]
    if (word === undefined) throw new Error(`BIP-39 index out of range: ${idx}`)
    words.push(word)
  }
  return words
}

/**
 * Decodes a 24-word BIP-39 mnemonic back to the 32-byte seed.
 * Validates the checksum.
 */
export async function decodeBip39(words: string[]): Promise<Uint8Array> {
  if (words.length !== 24) {
    throw new Error(`Expected 24 words, got ${words.length}`)
  }

  // Convert words to indices
  const indices: number[] = words.map((word) => {
    const idx = WORDLIST.indexOf(word.toLowerCase())
    if (idx === -1) throw new Error(`Unknown BIP-39 word: "${word}"`)
    return idx
  })

  // Convert 24 × 11-bit indices to bits (264 bits total)
  const bits: number[] = []
  for (const idx of indices) {
    for (let b = 10; b >= 0; b--) {
      bits.push((idx >> b) & 1)
    }
  }

  // Split into 32-byte entropy + 8-bit checksum
  const entropy = new Uint8Array(32)
  for (let i = 0; i < 32; i++) {
    let byte = 0
    for (let b = 0; b < 8; b++) {
      byte = (byte << 1) | (bits[i * 8 + b]! ?? 0)
    }
    entropy[i] = byte
  }

  // Validate checksum
  const entropyBuf = entropy.buffer.slice(entropy.byteOffset, entropy.byteOffset + entropy.byteLength) as ArrayBuffer
  const hashBuf = await crypto.subtle.digest('SHA-256', entropyBuf)
  const hash = new Uint8Array(hashBuf)
  const expectedCheckByte = hash[0]!

  let actualCheck = 0
  for (let b = 0; b < 8; b++) {
    actualCheck = (actualCheck << 1) | (bits[256 + b]! ?? 0)
  }

  if (actualCheck !== expectedCheckByte) {
    throw new Error('BIP-39 checksum mismatch — invalid mnemonic')
  }

  return entropy
}