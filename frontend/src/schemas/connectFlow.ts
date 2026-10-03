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
