/**
 * Zustand store for cryptographic session state.
 *
 * SECURITY: NO persist middleware. All crypto material lives in RAM only.
 * On page refresh or lock(), everything is cleared.
 */
import { create } from "zustand";

interface WalletKeyEntry {
  key: Uint8Array;
  expiresAt: number; // Unix timestamp ms
}

interface CryptoState {
  /** RSA private key bytes (PKCS8 DER), null when locked */
  rsaPrivateKey: Uint8Array | null;
  /** Symmetric key bytes (32 bytes), null when locked */
  symKey: Uint8Array | null;
  /** RSA public key bytes (SPKI DER), set after unlock */
  rsaPublicKey: Uint8Array | null;
  /** Per-wallet key cache with 10-minute TTL */
  walletKeys: Map<string, WalletKeyEntry>;
  /** Whether the vault is currently unlocked */
  isUnlocked: boolean;

  /** Set crypto state after successful unlock or bootstrap */
  setUnlocked: (
    rsaPriv: Uint8Array,
    symKey: Uint8Array,
    rsaPub: Uint8Array,
  ) => void;

  /** Cache a wallet key (10-minute TTL) */
  cacheWalletKey: (walletId: string, key: Uint8Array) => void;

  /** Retrieve a cached wallet key if not expired */
  getWalletKey: (walletId: string) => Uint8Array | null;

  /** Lock the vault — clears ALL crypto material from memory */
  lock: () => void;
}

export const useCryptoStore = create<CryptoState>()((set, get) => ({
  rsaPrivateKey: null,
  symKey: null,
  rsaPublicKey: null,
  walletKeys: new Map(),
  isUnlocked: false,

  setUnlocked: (rsaPriv, symKey, rsaPub) =>
    set({
      rsaPrivateKey: rsaPriv,
      symKey: symKey,
      rsaPublicKey: rsaPub,
      isUnlocked: true,
    }),

  cacheWalletKey: (walletId, key) => {
    const map = new Map(get().walletKeys);
    map.set(walletId, { key, expiresAt: Date.now() + 10 * 60 * 1000 });
    set({ walletKeys: map });
  },

  getWalletKey: (walletId) => {
    const entry = get().walletKeys.get(walletId);
    if (!entry) return null;
    if (entry.expiresAt < Date.now()) {
      // Evict expired entry
      const map = new Map(get().walletKeys);
      map.delete(walletId);
      set({ walletKeys: map });
      return null;
    }
    return entry.key;
  },

  lock: () =>
    set({
      rsaPrivateKey: null,
      symKey: null,
      rsaPublicKey: null,
      walletKeys: new Map(),
      isUnlocked: false,
    }),
}));
