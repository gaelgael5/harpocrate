/**
 * Zod schemas for /v1/apps endpoint.
 * Mirror of backend app/models/api/apps.py.
 */
import { z } from 'zod'

export const AppEntrySchema = z.object({
  key: z.string().min(1),
  label: z.string().min(1),
  icon: z.string().url(),
  url: z.string().url(),
})

export const AppsResponseSchema = z.object({
  urls: z.array(AppEntrySchema),
})

export type AppEntry = z.infer<typeof AppEntrySchema>
export type AppsResponse = z.infer<typeof AppsResponseSchema>
