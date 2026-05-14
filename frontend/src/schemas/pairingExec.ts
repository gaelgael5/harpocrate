import { z } from "zod";

export const StepStartedEventSchema = z.object({
  type: z.literal("step_started"),
  step_idx: z.number().int().min(0),
  title: z.string(),
  command: z.string(),
});
export const StepDoneEventSchema = z.object({
  type: z.literal("step_done"),
  step_idx: z.number().int().min(0),
  exit_code: z.number().int(),
  stdout: z.string(),
  stderr: z.string(),
});
export const StepErrorEventSchema = z.object({
  type: z.literal("step_error"),
  step_idx: z.number().int().min(0),
  exit_code: z.number().int(),
  stdout: z.string(),
  stderr: z.string(),
  error_type: z.string(),
});
export const ExecutionCompleteEventSchema = z.object({
  type: z.literal("execution_complete"),
});

export type StepStartedEvent = z.infer<typeof StepStartedEventSchema>;
export type StepDoneEvent = z.infer<typeof StepDoneEventSchema>;
export type StepErrorEvent = z.infer<typeof StepErrorEventSchema>;
export type ExecutionCompleteEvent = z.infer<typeof ExecutionCompleteEventSchema>;

export type ExecEvent = StepStartedEvent | StepDoneEvent | StepErrorEvent | ExecutionCompleteEvent;

export function parseExecEvent(raw: unknown): ExecEvent | null {
  for (const sch of [
    StepStartedEventSchema,
    StepDoneEventSchema,
    StepErrorEventSchema,
    ExecutionCompleteEventSchema,
  ]) {
    const r = sch.safeParse(raw);
    if (r.success) return r.data;
  }
  return null;
}
