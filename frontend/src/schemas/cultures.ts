/**
 * Cultures activables — /v1/admin/cultures (épic « Cultures et templates Listmonk
 * paramétrés en base », feature 1).
 */
import { z } from "zod";

export const CultureSchema = z.object({
  code: z.string(),
  english_name: z.string(),
  native_name: z.string().nullable(),
  enabled: z.boolean(),
  is_default: z.boolean(),
  updated_at: z.string(),
});
export type Culture = z.infer<typeof CultureSchema>;

export const CultureListSchema = z.object({
  items: z.array(CultureSchema),
});
export type CultureList = z.infer<typeof CultureListSchema>;

/** `is_default` n'accepte que `true` : on change de défaut en désignant une autre culture. */
export interface CultureUpdateBody {
  enabled?: boolean;
  is_default?: true;
}
