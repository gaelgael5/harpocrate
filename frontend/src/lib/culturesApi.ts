/**
 * Client API des cultures — /v1/admin/cultures (feature 1).
 */
import { api } from "@/lib/api-client";
import {
  CultureListSchema,
  CultureSchema,
  type Culture,
  type CultureList,
  type CultureUpdateBody,
} from "@/schemas/cultures";

const BASE = "/admin/cultures";

export async function fetchCultures(): Promise<CultureList> {
  return CultureListSchema.parse(await api.get<unknown>(BASE));
}

export async function updateCulture(
  code: string,
  body: CultureUpdateBody,
): Promise<Culture> {
  return CultureSchema.parse(await api.patch<unknown>(`${BASE}/${code}`, body));
}
