/**
 * Paramétrage Listmonk — /v1/admin/listmonk (épic « Cultures et templates Listmonk
 * paramétrés en base », feature 2).
 *
 * La connexion (URL, utilisateur, token) se règle ici aussi (feature 3). Le token
 * s'écrit mais ne se relit jamais : le serveur ne le renvoie pas au navigateur.
 */
import { z } from "zod";

export const ListmonkTemplateSchema = z.object({
  purpose: z.string(),
  culture_code: z.string(),
  template_id: z.number().int().positive(),
  updated_at: z.string(),
});
export type ListmonkTemplate = z.infer<typeof ListmonkTemplateSchema>;

/** Connexion montrée à l'admin : le token n'y figure jamais, seulement s'il est lisible. */
export const ListmonkConnectionSchema = z.object({
  url: z.string(),
  api_user: z.string(),
  token_readable: z.boolean(),
  updated_at: z.string(),
});
export type ListmonkConnection = z.infer<typeof ListmonkConnectionSchema>;

export const ListmonkSettingsSchema = z.object({
  connection: ListmonkConnectionSchema.nullable(),
  purposes: z.array(z.string()),
  templates: z.array(ListmonkTemplateSchema),
});
export type ListmonkSettings = z.infer<typeof ListmonkSettingsSchema>;

// Borne haute = INTEGER PostgreSQL, comme côté backend.
export const MAX_TEMPLATE_ID = 2_147_483_647;

/** Corps de PUT /connection et POST /connection/test ; sans `token`, celui enregistré sert. */
export interface ListmonkConnectionBody {
  url: string;
  api_user: string;
  token?: string;
}

export const ConnectionTestResultSchema = z.object({
  ok: z.boolean(),
  http_status: z.number().int().nullable(),
});
export type ConnectionTestResult = z.infer<typeof ConnectionTestResultSchema>;
