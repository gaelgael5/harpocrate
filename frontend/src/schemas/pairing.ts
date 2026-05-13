import { z } from "zod";

const PairingStatusEnum = z.enum([
  "pending",
  "confirmed",
  "wizard",
  "completed",
  "expired",
  "failed",
]);
const PairingRoleEnum = z.enum(["master", "standby"]);

export const PairingInitResponseSchema = z.object({
  session_id: z.string().uuid(),
  code: z.string().regex(/^\d{4}$/),
  expires_in_seconds: z.number().int().positive(),
});
export type PairingInitResponse = z.infer<typeof PairingInitResponseSchema>;

export const PairingStatusSchema = z.object({
  session_id: z.string().uuid(),
  role: PairingRoleEnum,
  status: PairingStatusEnum,
  partner_url: z.string().nullable(),
  current_step_idx: z.number().int().min(0),
  expires_at: z.string().datetime({ offset: true }),
});
export type PairingStatus = z.infer<typeof PairingStatusSchema>;

export const PairingStepSchema = z.object({
  idx: z.number().int().min(0),
  title: z.string(),
  command: z.string(),
  hint: z.string().optional(),
});
export type PairingStep = z.infer<typeof PairingStepSchema>;

export const PairingStepsResponseSchema = z.object({
  steps: z.array(PairingStepSchema),
  current_step_idx: z.number().int().min(0),
  status: PairingStatusEnum,
});
export type PairingStepsResponse = z.infer<typeof PairingStepsResponseSchema>;

export const PairingAcceptResponseSchema = z.object({
  session_id: z.string().uuid(),
});
export type PairingAcceptResponse = z.infer<typeof PairingAcceptResponseSchema>;

// ─── V2 — échange d'URL d'appairage (LOT 5) ──────────────────────────────────

export const PairingInitV2ResponseSchema = z.object({
  session_id: z.string().uuid(),
  pairing_url: z.string().url(),
  expires_in_seconds: z.number().int().positive(),
});
export type PairingInitV2Response = z.infer<typeof PairingInitV2ResponseSchema>;
