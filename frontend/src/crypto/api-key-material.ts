/**
 * Éléments cryptographiques d'une API key, calculés dans le navigateur.
 *
 * Partagé par la page API keys (création manuelle) et par le flux « Se connecter avec
 * Harpocrate » (feature 4) :
 * 1. auth_secret, decryption_key (dkey), auth_salt aléatoires ;
 * 2. auth_hash = Argon2id(auth_secret) — le serveur ne garde que ce hash ;
 * 3. encrypted_wallet_key = AES-GCM(wallet_key, dkey) ;
 * 4. encrypted_decryption_key_for_owner = RSA-OAEP(dkey, clé publique du propriétaire).
 * La dkey en clair est rendue À PART du corps de requête : c'est l'appelant qui décide
 * si elle part au serveur (création manuelle) ou non (flux de connexion, D4).
 */
import { DEFAULT_KDF_PARAMS, hashAuthSecret } from "@/crypto/argon2";
import { aesGcmEncrypt } from "@/crypto/aes-gcm";
import { randomBytes, toBase64 } from "@/crypto/helpers";
import { rsaOaepEncrypt } from "@/crypto/rsa-oaep";

/** Encode des bytes en base64url sans padding (segments du token hrpv_*). */
export function toBase64Url(bytes: Uint8Array): string {
  return toBase64(bytes)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=/g, "");
}

/** Corps commun aux deux routes de création de clé — sans la dkey. */
export interface ApiKeyMaterialBody {
  auth_secret: string;
  auth_hash: string;
  auth_salt: string;
  auth_kdf_memory_kb: number;
  auth_kdf_iterations: number;
  auth_kdf_parallelism: number;
  encrypted_wallet_key: string;
  encrypted_decryption_key_for_owner: string;
}

export interface ApiKeyMaterial {
  body: ApiKeyMaterialBody;
  /** dkey en base64url : segment du token, à ne jamais journaliser. */
  decryptionKey: string;
}

export async function generateApiKeyMaterial(
  walletKey: Uint8Array,
  ownerRsaPublicKey: Uint8Array,
): Promise<ApiKeyMaterial> {
  const authSecret = toBase64Url(randomBytes(32));
  const decryptionKeyBytes = randomBytes(32);
  const authSalt = randomBytes(16);
  // Le backend vérifie avec Argon2id sur base64url(auth_secret) : même entrée ici.
  const authHashPhc = await hashAuthSecret(
    authSecret,
    authSalt,
    DEFAULT_KDF_PARAMS,
  );
  const encryptedWalletKey = await aesGcmEncrypt(walletKey, decryptionKeyBytes);
  const encryptedDkey = await rsaOaepEncrypt(
    decryptionKeyBytes,
    ownerRsaPublicKey,
  );
  return {
    body: {
      auth_secret: authSecret,
      auth_hash: btoa(authHashPhc),
      auth_salt: toBase64(authSalt),
      auth_kdf_memory_kb: DEFAULT_KDF_PARAMS.memory_kb,
      auth_kdf_iterations: DEFAULT_KDF_PARAMS.iterations,
      auth_kdf_parallelism: DEFAULT_KDF_PARAMS.parallelism,
      encrypted_wallet_key: toBase64(encryptedWalletKey),
      encrypted_decryption_key_for_owner: toBase64(encryptedDkey),
    },
    decryptionKey: toBase64Url(decryptionKeyBytes),
  };
}
