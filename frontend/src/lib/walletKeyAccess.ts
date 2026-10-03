/**
 * Accès au wallet key en mémoire, pour les parcours qui ne vivent pas sur une page de
 * wallet (flux « Se connecter avec Harpocrate », feature 3-4).
 *
 * Le wallet key ne quitte jamais le navigateur : il est déchiffré depuis le grant de
 * l'utilisateur (RSA-OAEP) ou généré à la création du wallet, puis gardé dans le store
 * crypto (RAM), comme le font les pages de wallet.
 */
import { api } from "@/lib/api-client";
import { fromBase64, randomBytes, toBase64 } from "@/crypto/helpers";
import { rsaOaepDecrypt, rsaOaepEncrypt } from "@/crypto/rsa-oaep";
import { MyGrantResponseSchema } from "@/schemas/grants";
import { WalletCreateResponseSchema } from "@/schemas/wallets";
import { useCryptoStore } from "@/stores/crypto";

export class CryptoLockedError extends Error {
  constructor() {
    super("crypto_locked");
    this.name = "CryptoLockedError";
  }
}

export async function loadWalletKey(walletId: string): Promise<Uint8Array> {
  const store = useCryptoStore.getState();
  const cached = store.getWalletKey(walletId);
  if (cached) return cached;
  if (!store.rsaPrivateKey) throw new CryptoLockedError();
  const grant = MyGrantResponseSchema.parse(
    await api.get<unknown>(`/wallets/${walletId}/my-grant`),
  );
  const walletKey = await rsaOaepDecrypt(
    fromBase64(grant.encrypted_wallet_key),
    store.rsaPrivateKey,
  );
  store.cacheWalletKey(walletId, walletKey);
  return walletKey;
}

/** Crée un wallet (propriétaire : l'utilisateur, tous les droits) ; son key reste en RAM. */
export async function createWalletWithKey(
  name: string,
): Promise<{ walletId: string; walletKey: Uint8Array }> {
  const store = useCryptoStore.getState();
  if (!store.rsaPublicKey) throw new CryptoLockedError();
  const walletKey = randomBytes(32);
  const encrypted = await rsaOaepEncrypt(walletKey, store.rsaPublicKey);
  const { wallet_id: walletId } = WalletCreateResponseSchema.parse(
    await api.post<unknown>("/wallets", {
      name,
      description: null,
      tags: [],
      encrypted_wallet_key_for_owner: toBase64(encrypted),
      environment_id: null,
    }),
  );
  store.cacheWalletKey(walletId, walletKey);
  return { walletId, walletKey };
}
