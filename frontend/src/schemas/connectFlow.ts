/**
 * Réponses du flux « Se connecter avec Harpocrate » côté navigateur (features 2 à 4).
 */
import { z } from "zod";

export const AppPublicJwkSchema = z.object({
  kty: z.literal("EC"),
  crv: z.literal("P-256"),
  x: z.string(),
  y: z.string(),
  use: z.literal("enc").optional(),
  alg: z.literal("ECDH-ES").optional(),
  kid: z.string().optional(),
});
export type AppPublicJwk = z.infer<typeof AppPublicJwkSchema>;

export const ConnectRequestViewSchema = z.object({
  client: z.object({
    client_id: z.string(),
    name: z.string(),
    description: z.string().nullable(),
  }),
  redirect_uri: z.string(),
  requested_permissions: z.number().int(),
  requested_ttl_days: z.number().int().nullable(),
  app_public_jwk: AppPublicJwkSchema,
  expires_at: z.string(),
});
export type ConnectRequestView = z.infer<typeof ConnectRequestViewSchema>;

export const ConnectRedirectSchema = z.object({ redirect_to: z.string() });

export const ConnectApiKeyResponseSchema = z.object({
  api_key_id: z.string().uuid(),
  token: z.string(),
});
export type ConnectApiKeyResponse = z.infer<typeof ConnectApiKeyResponseSchema>;

/** Choix de l'utilisateur à l'écran de consentement (D3 : il ne peut que réduire). */
export interface ConnectDecision {
  wallet:
    | { kind: "existing"; walletId: string }
    | { kind: "new"; name: string };
  permissions: number;
  ttlDays: number | null;
}
