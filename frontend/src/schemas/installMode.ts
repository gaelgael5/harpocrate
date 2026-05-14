import { z } from "zod";

export const InstallModeResponseSchema = z.object({
  mode: z.enum(["docker_compose_auto", "native"]),
  docker_socket_accessible: z.boolean(),
  pg_container_data_host_path: z.string().nullable(),
});
export type InstallModeResponse = z.infer<typeof InstallModeResponseSchema>;
