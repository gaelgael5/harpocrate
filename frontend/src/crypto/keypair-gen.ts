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
 * - RSA-PSS / RSA-OAEP : universellement supporté
 *
 * Sur navigateur trop ancien : exception explicite avec message clair.
 */

// Note : pkijs + asn1js (~80 KB) sont importés dynamiquement à l'intérieur
// de generateTlsServerKeypair() — ils ne sont chargés QUE lors de la
// génération TLS, pas au boot de l'app ni pour WireGuard/SSH (qui n'utilisent
// que WebCrypto natif). Vite émet un chunk JS séparé.

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

// ─── TLS server (auto-signé via pkijs) ───────────────────────────────────────

export interface TlsServerKeypair {
  /** Certificat X.509 PEM (-----BEGIN CERTIFICATE-----...). */
  certificate: string
  /** Clé privée PEM PKCS#8 (-----BEGIN PRIVATE KEY-----...). */
  privateKey: string
  /** Empreinte SHA-256 du DER (64 chars hex). */
  fingerprintSha256: string
  notBefore: string  // ISO date YYYY-MM-DD
  notAfter: string   // ISO date YYYY-MM-DD
}

export interface TlsGenerationOptions {
  commonName: string
  /** Liste de DNS et/ou IPs (les IPs sont auto-détectées par regex IPv4/IPv6). */
  subjectAlternativeNames?: string[]
  /** Validité en jours (défaut 365). */
  validityDays?: number
  /** Taille de clé RSA en bits (2048, 3072 ou 4096 — défaut 4096). */
  keySize?: 2048 | 3072 | 4096
}

const IPV4_RE = /^(\d{1,3}\.){3}\d{1,3}$/
const IPV6_RE = /^[0-9a-fA-F:]+$/

function pemWrap(label: string, derBuffer: ArrayBuffer): string {
  let s = ''
  const view = new Uint8Array(derBuffer)
  for (const b of view) s += String.fromCharCode(b)
  const b64 = btoa(s)
  const wrapped = b64.match(/.{1,64}/g)?.join('\n') ?? b64
  return `-----BEGIN ${label}-----\n${wrapped}\n-----END ${label}-----\n`
}

async function fingerprintHex(buf: ArrayBuffer): Promise<string> {
  const sha = await globalThis.crypto.subtle.digest('SHA-256', buf)
  return Array.from(new Uint8Array(sha))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('')
}

/**
 * Génère un certificat TLS serveur RSA auto-signé via pkijs + WebCrypto.
 *
 * Usage type : certificat "lab" / dev / mTLS interne. Pour la prod publique,
 * utiliser Let's Encrypt et uploader le résultat ici.
 */
export async function generateTlsServerKeypair(
  options: TlsGenerationOptions,
): Promise<TlsServerKeypair> {
  if (typeof globalThis.crypto?.subtle === 'undefined') {
    throw new Error('Web Crypto API unavailable in this browser')
  }
  const cn = options.commonName.trim()
  if (!cn) throw new Error('commonName is required')
  const sans = (options.subjectAlternativeNames ?? []).map((s) => s.trim()).filter(Boolean)
  const validityDays = options.validityDays ?? 365
  const keySize = options.keySize ?? 4096

  // Imports dynamiques — chargent ~80 KB de JS uniquement quand on génère
  // un TLS, pas au démarrage. Vite/esbuild émet automatiquement un chunk.
  const [pkijs, asn1js] = await Promise.all([import('pkijs'), import('asn1js')])

  // 1. Génère la paire RSA-PSS via WebCrypto (signature SHA-256)
  const kp = (await globalThis.crypto.subtle.generateKey(
    {
      name: 'RSASSA-PKCS1-v1_5',
      modulusLength: keySize,
      publicExponent: new Uint8Array([0x01, 0x00, 0x01]),
      hash: 'SHA-256',
    },
    true,
    ['sign', 'verify'],
  )) as CryptoKeyPair

  // 2. Construit le certificat via pkijs
  const cert = new pkijs.Certificate()
  cert.version = 2  // X.509 v3

  // Numéro de série aléatoire 16 bytes (positive integer)
  const serialBytes = globalThis.crypto.getRandomValues(new Uint8Array(16))
  // Forcer positif (high bit à 0). serialBytes[0] est toujours défini ici (taille 16).
  serialBytes[0] = (serialBytes[0] ?? 0) & 0x7f
  cert.serialNumber = new asn1js.Integer({ valueHex: serialBytes })

  // Subject + Issuer (auto-signé : identiques)
  const cnAttr = new pkijs.AttributeTypeAndValue({
    type: '2.5.4.3',  // commonName
    value: new asn1js.Utf8String({ value: cn }),
  })
  cert.subject.typesAndValues.push(cnAttr)
  cert.issuer.typesAndValues.push(
    new pkijs.AttributeTypeAndValue({
      type: '2.5.4.3',
      value: new asn1js.Utf8String({ value: cn }),
    }),
  )

  // Validité
  const now = new Date()
  const notAfter = new Date(now.getTime() + validityDays * 24 * 60 * 60 * 1000)
  cert.notBefore.value = now
  cert.notAfter.value = notAfter

  // Charge la clé publique dans le SubjectPublicKeyInfo
  await cert.subjectPublicKeyInfo.importKey(kp.publicKey)

  // ── Extensions ─────────────────────────────────────────────────────────
  cert.extensions = []

  // Basic constraints : pas une CA
  const basicConstr = new pkijs.BasicConstraints({ cA: false })
  cert.extensions.push(
    new pkijs.Extension({
      extnID: '2.5.29.19',
      critical: true,
      extnValue: basicConstr.toSchema().toBER(false),
      parsedValue: basicConstr,
    }),
  )

  // Key usage : digitalSignature + keyEncipherment
  const keyUsageBits = new Uint8Array([0]) // 1 byte
  // bit 0 (digitalSignature) + bit 2 (keyEncipherment) = 0xA0 (DER bit string)
  keyUsageBits[0] = 0b10100000
  const keyUsage = new asn1js.BitString({ valueHex: keyUsageBits })
  cert.extensions.push(
    new pkijs.Extension({
      extnID: '2.5.29.15',
      critical: true,
      extnValue: keyUsage.toBER(false),
      parsedValue: keyUsage,
    }),
  )

  // Extended key usage : serverAuth + clientAuth
  const extKeyUsage = new pkijs.ExtKeyUsage({
    keyPurposes: ['1.3.6.1.5.5.7.3.1', '1.3.6.1.5.5.7.3.2'],
  })
  cert.extensions.push(
    new pkijs.Extension({
      extnID: '2.5.29.37',
      critical: false,
      extnValue: extKeyUsage.toSchema().toBER(false),
      parsedValue: extKeyUsage,
    }),
  )

  // Subject Alternative Names — ajoute le CN comme DNS si pas déjà présent
  const sansFinal = sans.length > 0 ? sans : [cn]
  const altNames = new pkijs.GeneralNames({
    names: sansFinal.map((value) => {
      if (IPV4_RE.test(value)) {
        const octets = value.split('.').map((o) => parseInt(o, 10))
        return new pkijs.GeneralName({
          type: 7,
          value: new asn1js.OctetString({ valueHex: new Uint8Array(octets) }),
        })
      }
      if (IPV6_RE.test(value) && value.includes(':')) {
        // Implementation IPv6 simple : on n'expand pas, on rejette les formes complexes
        // pour éviter une lib supplémentaire — l'admin peut fallback en DNS.
        const groups = value.split(':')
        if (groups.length !== 8 || groups.some((g) => !/^[0-9a-fA-F]{1,4}$/.test(g))) {
          throw new Error(`IPv6 must be in fully-expanded form (got ${value})`)
        }
        const bytes = new Uint8Array(16)
        groups.forEach((g, i) => {
          const n = parseInt(g, 16)
          bytes[i * 2] = (n >> 8) & 0xff
          bytes[i * 2 + 1] = n & 0xff
        })
        return new pkijs.GeneralName({
          type: 7,
          value: new asn1js.OctetString({ valueHex: bytes }),
        })
      }
      // dNSName par défaut
      return new pkijs.GeneralName({ type: 2, value })
    }),
  })
  cert.extensions.push(
    new pkijs.Extension({
      extnID: '2.5.29.17',
      critical: false,
      extnValue: altNames.toSchema().toBER(false),
      parsedValue: altNames,
    }),
  )

  // 3. Signe le certificat
  await cert.sign(kp.privateKey, 'SHA-256')

  // 4. Encode certificat (DER → PEM) et clé privée (PKCS#8 → PEM)
  const certDer = cert.toSchema(true).toBER(false)
  const certPem = pemWrap('CERTIFICATE', certDer)
  const fingerprintHexStr = await fingerprintHex(certDer)

  const pkcs8 = await globalThis.crypto.subtle.exportKey('pkcs8', kp.privateKey)
  const keyPem = pemWrap('PRIVATE KEY', pkcs8)

  return {
    certificate: certPem,
    privateKey: keyPem,
    fingerprintSha256: fingerprintHexStr,
    notBefore: now.toISOString().slice(0, 10),
    notAfter: notAfter.toISOString().slice(0, 10),
  }
}
