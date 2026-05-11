/**
 * API client for /v1/apps — cross-suite launcher menu.
 *
 * Validates the response through the Zod schema.
 * On validation failure, silently returns an empty list so the button hides.
 */
import { api } from "@/lib/api-client";
import { AppsResponseSchema, type AppsResponse } from "@/schemas/apps";

const _EMPTY: AppsResponse = { urls: [] };

export async function fetchApps(): Promise<AppsResponse> {
  const raw = await api.get<unknown>("/apps");
  const result = AppsResponseSchema.safeParse(raw);
  if (!result.success) {
    return _EMPTY;
  }
  return result.data;
}
