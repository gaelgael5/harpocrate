import { api } from "@/lib/api-client";
import { InstallModeResponseSchema, type InstallModeResponse } from "@/schemas/installMode";

export async function fetchInstallMode(): Promise<InstallModeResponse> {
  const raw = await api.get<unknown>("/admin/install-mode");
  return InstallModeResponseSchema.parse(raw);
}
