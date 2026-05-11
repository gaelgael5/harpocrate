import { describe, it, expect } from "vitest";
import {
  MaintenanceStatusSchema,
  BackupListResponseSchema,
} from "@/schemas/admin";

describe("admin schemas", () => {
  it("parses a maintenance status response", () => {
    const raw = {
      active: false,
      reason: null,
      started_at: null,
      effective_at: null,
      estimated_end_at: null,
    };
    const parsed = MaintenanceStatusSchema.parse(raw);
    expect(parsed.active).toBe(false);
  });

  it("parses a backup list response", () => {
    const raw = {
      backups: [
        {
          id: "aaaaaaaa-0000-0000-0000-000000000001",
          filename: "harpocrate-backup-2026-01-01-12-00-00.tar.age",
          size_bytes: 123456,
          checksum_sha256: "deadbeef",
          description: "test",
          created_at: "2026-01-01T12:00:00Z",
          created_by_user_id: null,
          imported: false,
          manifest: null,
        },
      ],
    };
    const parsed = BackupListResponseSchema.parse(raw);
    expect(parsed.backups).toHaveLength(1);
    expect(parsed.backups[0]!.filename).toBe(
      "harpocrate-backup-2026-01-01-12-00-00.tar.age",
    );
  });
});
