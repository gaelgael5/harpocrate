/**
 * Génération de paires de clés côté navigateur (zero-knowledge).
 *
 * Toutes les paires sont générées via WebCrypto natif — aucune clé privée
 * ne transite par le serveur. Le caller récupère la clé en clair, la chiffre
 * AES-GCM avec la wallet_key, puis envoie le blob chiffré à Harpocrate.
 *
 * Compat navigateurs (au 2026-05-07) :
 * - X25519 (WireGuard) : Chrome 134+, Firefox 130+, Safari 17.4+
 * - Ed25519 (SSH)      : Chrome 137+, Firefox 129+, Safari 17+
 *
 * Sur navigateur trop ancien : exception explicite avec message clair.
 */

import { toBase64 } from './helpers'

// ─── Helpers binaires ────────────────────────────────────────────────────────

function base64UrlToBytes(s: string): Uint8Array {
  let padded = s.replace(/-/g, '+').replace(/_/g, '/')
  while (padded.length % 4) padded += '='
  const bin = atob(padded)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out
}

function concat(...arrs: Uint8Array[]): Uint8Array {
  const total = arrs.reduce((acc, a) => acc + a.length, 0)
  const out = new Uint8Array(total)
  let off = 0
  for (const a of arrs) {
    out.set(a, off)
    off += a.length
  }
  return out
}

/** SSH wire format: uint32 BE length || bytes */
function packString(value: string | Uint8Array): Uint8Array {
  const bytes =
    typeof value === 'string' ? new TextEncoder().encode(value) : value
  const out = new Uint8Array(4 + bytes.length)
  new DataView(out.buffer).setUint32(0, bytes.length, false)
  out.set(bytes, 4)
  return out
}

function packUint32(n: number): Uint8Array {
  const out = new Uint8Array(4)
  new DataView(out.buffer).setUint32(0, n, false)
  return out
}

// ─── WireGuard ───────────────────────────────────────────────────────────────

export interface WireguardKeypair {
  /** Clé privée Curve25519, base64 standard (44 chars). */
  privateKey: string
  /** Clé publique Curve25519, base64 standard (44 chars). */
  publicKey: string
}

export async function generateWireguardKeypair(): Promise<WireguardKeypair> {
  if (typeof globalThis.crypto?.subtle === 'undefined') {
    throw new Error('Web Crypto API unavailable in this browser')
  }
  let kp: CryptoKeyPair
  try {
    kp = (await globalThis.crypto.subtle.generateKey(
      { name: 'X25519' },
      true,
      ['deriveBits'],
    )) as CryptoKeyPair
  } catch (err) {
    throw new Error(
      'X25519 not supported by this browser (need Chrome 134+, Firefox 130+, Safari 17.4+). ' +
        `Original error: ${String(err)}`,
      { cause: err },
    )
  }

  // La clé privée X25519 brute n'est pas exportable en 'raw' — on passe par jwk
  // dont le champ 'd' contient les 32 bytes en base64url.
  const privJwk = (await globalThis.crypto.subtle.exportKey(
    'jwk',
    kp.privateKey,
  )) as JsonWebKey
  if (!privJwk.d) {
    throw new Error('exported X25519 private key has no `d` field')
  }
  const privateBytes = base64UrlToBytes(privJwk.d)
  const publicBytesAb = await globalThis.crypto.subtle.exportKey(
    'raw',
    kp.publicKey,
  )
  const publicBytes = new Uint8Array(publicBytesAb)

  return {
    privateKey: toBase64(privateBytes),
    publicKey: toBase64(publicBytes),
  }
}

// ─── SSH Ed25519 ─────────────────────────────────────────────────────────────

export interface SshEd25519Keypair {
  /**
   * Clé privée au format OpenSSH PEM :
   *   -----BEGIN OPENSSH PRIVATE KEY-----
   *   <base64 sur lignes de 70 caractères>
   *   -----END OPENSSH PRIVATE KEY-----
   */
  privateKey: string
  /** Clé publique format `ssh-ed25519 <base64> <comment>` (ligne unique). */
  publicKey: string
  /** Empreinte format `SHA256:<base64-no-padding>` (idem ssh-keygen -lf). */
  fingerprint: string
}

/**
 * Génère une paire SSH Ed25519 et l'encode au format OpenSSH.
 *
 * `comment` est embarqué à la fois dans le bloc privé (visible avec
 * ssh-keygen -y) et à la fin de la ligne publique. Vide accepté.
 */
export async function generateSshEd25519Keypair(
  comment = '',
): Promise<SshEd25519Keypair> {
  if (typeof globalThis.crypto?.subtle === 'undefined') {
    throw new Error('Web Crypto API unavailable in this browser')
  }
  let kp: CryptoKeyPair
  try {
    kp = (await globalThis.crypto.subtle.generateKey(
      { name: 'Ed25519' },
      true,
      ['sign', 'verify'],
    )) as CryptoKeyPair
  } catch (err) {
    throw new Error(
      'Ed25519 not supported by this browser (need Chrome 137+, Firefox 129+, Safari 17+). ' +
        `Original error: ${String(err)}`,
      { cause: err },
    )
  }

  const pubAb = await globalThis.crypto.subtle.exportKey('raw', kp.publicKey)
  const pubBytes = new Uint8Array(pubAb)
  const privJwk = (await globalThis.crypto.subtle.exportKey(
    'jwk',
    kp.privateKey,
  )) as JsonWebKey
  if (!privJwk.d) {
    throw new Error('exported Ed25519 private key has no `d` field')
  }
  const privSeed = base64UrlToBytes(privJwk.d)

  // Public key blob : string("ssh-ed25519") || string(<pub 32 bytes>)
  const pubBlob = concat(packString('ssh-ed25519'), packString(pubBytes))

  // Public key text format
  const publicKeyText = `ssh-ed25519 ${toBase64(pubBlob)}${comment ? ` ${comment}` : ''}`

  // Fingerprint : SHA256(pubBlob) → base64 standard sans padding.
  // Cast en BufferSource — pubBlob.buffer peut être SharedArrayBuffer en types
  // stricts mais on a construit le Uint8Array nous-mêmes donc c'est un ArrayBuffer.
  const shaAb = await globalThis.crypto.subtle.digest(
    'SHA-256',
    pubBlob as unknown as BufferSource,
  )
  const fingerprint = `SHA256:${toBase64(new Uint8Array(shaAb)).replace(/=+$/, '')}`

  // ── OpenSSH private key block ───────────────────────────────────────────
  // openssh-key-v1\0 || ciphername("none") || kdfname("none") || kdfopts("")
  // || num_keys(1) || string(pubBlob) || string(encrypted_section)
  //
  // encrypted_section = checkint || checkint || string("ssh-ed25519")
  //                   || string(pub) || string(seed||pub) || string(comment)
  //                   || padding (1, 2, 3, ... pour aligner à 8 bytes)

  const checkint = globalThis.crypto.getRandomValues(new Uint8Array(4))
  const fullPriv = concat(privSeed, pubBytes) // ed25519 privée OpenSSH = seed||pub (64 bytes)

  const encryptedRaw = concat(
    checkint,
    checkint,
    packString('ssh-ed25519'),
    packString(pubBytes),
    packString(fullPriv),
    packString(comment),
  )
  const padLen = (8 - (encryptedRaw.length % 8)) % 8
  const padding = new Uint8Array(padLen)
  for (let i = 0; i < padLen; i++) padding[i] = i + 1
  const encrypted = concat(encryptedRaw, padding)

  const magic = new TextEncoder().encode('openssh-key-v1\0')
  const topLevel = concat(
    magic,
    packString('none'),
    packString('none'),
    packString(''),
    packUint32(1),
    packString(pubBlob),
    packString(encrypted),
  )

  const b64 = toBase64(topLevel)
  const wrapped = b64.match(/.{1,70}/g)?.join('\n') ?? b64
  const privateKeyText = `-----BEGIN OPENSSH PRIVATE KEY-----\n${wrapped}\n-----END OPENSSH PRIVATE KEY-----\n`

  return { privateKey: privateKeyText, publicKey: publicKeyText, fingerprint }
}
