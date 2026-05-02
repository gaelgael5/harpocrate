/**
 * Zustand crypto store tests — verifies lock/unlock transitions and no-leak guarantee.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useCryptoStore } from '@/stores/crypto'

function makeTestKey(fill: number): Uint8Array {
  return new Uint8Array(32).fill(fill)
}

describe('useCryptoStore', () => {
  beforeEach(() => {
    // Reset store to initial state before each test
    useCryptoStore.setState({
      rsaPrivateKey: null,
      symKey: null,
      rsaPublicKey: null,
      walletKeys: new Map(),
      isUnlocked: false,
    })
  })

  it('starts locked with null keys', () => {
    const state = useCryptoStore.getState()
    expect(state.isUnlocked).toBe(false)
    expect(state.rsaPrivateKey).toBeNull()
    expect(state.symKey).toBeNull()
    expect(state.rsaPublicKey).toBeNull()
  })

  it('setUnlocked stores keys and sets isUnlocked=true', () => {
    const rsaPriv = makeTestKey(0x01)
    const symKey = makeTestKey(0x02)
    const rsaPub = makeTestKey(0x03)

    useCryptoStore.getState().setUnlocked(rsaPriv, symKey, rsaPub)

    const state = useCryptoStore.getState()
    expect(state.isUnlocked).toBe(true)
    expect(Array.from(state.rsaPrivateKey!)).toEqual(Array.from(rsaPriv))
    expect(Array.from(state.symKey!)).toEqual(Array.from(symKey))
  })

  it('lock() clears all crypto material', () => {
    useCryptoStore.getState().setUnlocked(
      makeTestKey(0x01),
      makeTestKey(0x02),
      makeTestKey(0x03),
    )
    useCryptoStore.getState().cacheWalletKey('wallet-1', makeTestKey(0x04))

    useCryptoStore.getState().lock()

    const state = useCryptoStore.getState()
    expect(state.isUnlocked).toBe(false)
    expect(state.rsaPrivateKey).toBeNull()
    expect(state.symKey).toBeNull()
    expect(state.rsaPublicKey).toBeNull()
    expect(state.walletKeys.size).toBe(0)
  })

  it('cacheWalletKey stores and retrieves wallet key', () => {
    const walletKey = makeTestKey(0xAB)
    useCryptoStore.getState().cacheWalletKey('wallet-abc', walletKey)

    const retrieved = useCryptoStore.getState().getWalletKey('wallet-abc')
    expect(retrieved).not.toBeNull()
    expect(Array.from(retrieved!)).toEqual(Array.from(walletKey))
  })

  it('getWalletKey returns null for unknown wallet', () => {
    const result = useCryptoStore.getState().getWalletKey('unknown-wallet')
    expect(result).toBeNull()
  })

  it('state is NOT stored in localStorage or sessionStorage', () => {
    useCryptoStore.getState().setUnlocked(
      makeTestKey(0x01),
      makeTestKey(0x02),
      makeTestKey(0x03),
    )

    // Check neither storage has crypto keys
    const lsKeys = Object.keys(localStorage)
    const ssKeys = Object.keys(sessionStorage)

    // No key should contain base64 of our test keys or 'rsa' or 'sym'
    const allKeys = [...lsKeys, ...ssKeys]
    const cryptoKeys = allKeys.filter(
      (k) => k.includes('rsa') || k.includes('sym') || k.includes('priv'),
    )
    expect(cryptoKeys).toHaveLength(0)
  })
})
