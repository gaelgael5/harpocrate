import { describe, it, expect } from "vitest";
import { RemoteBackupConnectionSchema } from "./admin";

describe("RemoteBackupConnectionSchema", () => {
  const now = new Date().toISOString();

  it("parse une connexion gdrive avec tous les champs", () => {
    const data = {
      id: "550e8400-e29b-41d4-a716-446655440000",
      name: "My Drive",
      kind: "gdrive",
      config: {
        client_id: "client-id-12345",
        redirect_uri: "https://harpo.example.com/callback",
        folder_name: "Backups",
        folder_id: "folder-id-67890",
        user_email: "admin@example.com",
      },
      created_at: now,
      updated_at: now,
      created_by_user_id: null,
      deleted_at: null,
      has_credentials: true,
    };

    const result = RemoteBackupConnectionSchema.parse(data);
    expect(result.kind).toBe("gdrive");
    expect(result.name).toBe("My Drive");
    expect(result.config.client_id).toBe("client-id-12345");
    expect(result.has_credentials).toBe(true);
  });

  it("parse une connexion gdrive avec champs optionnels absents", () => {
    const data = {
      id: "550e8400-e29b-41d4-a716-446655440001",
      name: "Simple Drive",
      kind: "gdrive",
      config: {
        client_id: "cid",
        redirect_uri: "https://harpo.example.com/cb",
        folder_name: "F",
      },
      created_at: now,
      updated_at: now,
      created_by_user_id: null,
      deleted_at: null,
    };

    const result = RemoteBackupConnectionSchema.parse(data);
    expect(result.kind).toBe("gdrive");
    expect(result.config.folder_id).toBeUndefined();
    expect(result.config.user_email).toBeUndefined();
    expect(result.has_credentials).toBe(false);
  });

  it("valide les autres kinds existants (sftp, s3, ftps)", () => {
    const kinds: Array<"sftp" | "s3" | "ftps"> = ["sftp", "s3", "ftps"];

    kinds.forEach((kind) => {
      const data = {
        id: "550e8400-e29b-41d4-a716-446655440002",
        name: `Test ${kind}`,
        kind,
        config: { some: "config" },
        created_at: now,
        updated_at: now,
        created_by_user_id: null,
        deleted_at: null,
      };

      const result = RemoteBackupConnectionSchema.parse(data);
      expect(result.kind).toBe(kind);
    });
  });

  it("rejette un kind invalide", () => {
    const data = {
      id: "550e8400-e29b-41d4-a716-446655440003",
      name: "Invalid",
      kind: "invalid_kind",
      config: {},
      created_at: now,
      updated_at: now,
      created_by_user_id: null,
      deleted_at: null,
    };

    expect(() => RemoteBackupConnectionSchema.parse(data)).toThrow();
  });
});
