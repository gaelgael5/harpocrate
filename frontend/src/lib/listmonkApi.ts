/**
 * Client API du paramétrage Listmonk — /v1/admin/listmonk (feature 2).
 */
import { api } from "@/lib/api-client";
import {
  ListmonkSettingsSchema,
  ListmonkTemplateSchema,
  type ListmonkSettings,
  type ListmonkTemplate,
} from "@/schemas/listmonk";

const BASE = "/admin/listmonk";

export async function fetchListmonkSettings(): Promise<ListmonkSettings> {
  return ListmonkSettingsSchema.parse(await api.get<unknown>(BASE));
}

export async function setListmonkTemplate(
  purpose: string,
  cultureCode: string,
  templateId: number,
): Promise<ListmonkTemplate> {
  return ListmonkTemplateSchema.parse(
    await api.put<unknown>(`${BASE}/templates/${purpose}/${cultureCode}`, {
      template_id: templateId,
    }),
  );
}

export async function deleteListmonkTemplate(
  purpose: string,
  cultureCode: string,
): Promise<void> {
  await api.delete<void>(`${BASE}/templates/${purpose}/${cultureCode}`);
}
