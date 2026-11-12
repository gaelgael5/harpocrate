/**
 * Paramétrage Listmonk — /v1/admin/listmonk (épic « Cultures et templates Listmonk
 * paramétrés en base », feature 2).
 *
 * `configured` et `url` décrivent la connexion posée dans le .env de l'hôte, en lecture
 * seule ; l'utilisateur et le token Listmonk ne sont jamais renvoyés au navigateur.
 */
import { z } from "zod";

export const ListmonkTemplateSchema = z.object({
  purpose: z.string(),
  culture_code: z.string(),
  template_id: z.number().int().positive(),
  updated_at: z.string(),
});
export type ListmonkTemplate = z.infer<typeof ListmonkTemplateSchema>;

export const ListmonkSettingsSchema = z.object({
  configured: z.boolean(),
  url: z.string(),
  purposes: z.array(z.string()),
  templates: z.array(ListmonkTemplateSchema),
});
export type ListmonkSettings = z.infer<typeof ListmonkSettingsSchema>;

// Borne haute = INTEGER PostgreSQL, comme côté backend.
export const MAX_TEMPLATE_ID = 2_147_483_647;
