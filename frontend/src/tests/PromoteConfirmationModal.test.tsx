/**
 * Tests PromoteConfirmationModal — vérifie le double-check anti-split-brain.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MantineProvider } from "@mantine/core";
import React from "react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const parts = key.split(".");
      return parts[parts.length - 1] ?? key;
    },
    i18n: { language: "fr", changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

import { PromoteConfirmationModal } from "@/components/PromoteConfirmationModal";

function renderModal(props: Partial<React.ComponentProps<typeof PromoteConfirmationModal>> = {}) {
  const defaults = {
    opened: true,
    masterUrl: "https://old-master.example/",
    onClose: vi.fn(),
    onSubmit: vi.fn(),
  };
  return render(
    <MantineProvider>
      <PromoteConfirmationModal {...defaults} {...props} />
    </MantineProvider>,
  );
}

describe("PromoteConfirmationModal", () => {
  it("disables submit until both checkboxes are checked", async () => {
    renderModal();
    const submit = screen.getByRole("button", { name: "submit" });
    expect(submit).toBeDisabled();

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes).toHaveLength(2);

    await userEvent.click(checkboxes[0]!);
    expect(submit).toBeDisabled();

    await userEvent.click(checkboxes[1]!);
    expect(submit).toBeEnabled();
  });

  it("calls onSubmit when both checkboxes are checked and submit is clicked", async () => {
    const onSubmit = vi.fn();
    renderModal({ onSubmit });

    const checkboxes = screen.getAllByRole("checkbox");
    await userEvent.click(checkboxes[0]!);
    await userEvent.click(checkboxes[1]!);
    await userEvent.click(screen.getByRole("button", { name: "submit" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("does NOT call onSubmit when only one checkbox is checked", async () => {
    const onSubmit = vi.fn();
    renderModal({ onSubmit });

    const checkboxes = screen.getAllByRole("checkbox");
    await userEvent.click(checkboxes[0]!);
    // submit reste disabled — userEvent.click sur un disabled button n'appelle pas le handler
    const submit = screen.getByRole("button", { name: "submit" });
    expect(submit).toBeDisabled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("resets checkboxes when modal is closed and reopened", async () => {
    const { rerender } = render(
      <MantineProvider>
        <PromoteConfirmationModal
          opened={true}
          masterUrl="https://m/"
          onClose={vi.fn()}
          onSubmit={vi.fn()}
        />
      </MantineProvider>,
    );
    const checkboxes = screen.getAllByRole("checkbox");
    await userEvent.click(checkboxes[0]!);
    expect(checkboxes[0]).toBeChecked();

    // Close
    rerender(
      <MantineProvider>
        <PromoteConfirmationModal
          opened={false}
          masterUrl="https://m/"
          onClose={vi.fn()}
          onSubmit={vi.fn()}
        />
      </MantineProvider>,
    );
    // Reopen
    rerender(
      <MantineProvider>
        <PromoteConfirmationModal
          opened={true}
          masterUrl="https://m/"
          onClose={vi.fn()}
          onSubmit={vi.fn()}
        />
      </MantineProvider>,
    );
    const fresh = screen.getAllByRole("checkbox");
    expect(fresh[0]).not.toBeChecked();
    expect(fresh[1]).not.toBeChecked();
  });

  it("disables both buttons when submitting=true", () => {
    renderModal({ submitting: true });
    expect(screen.getByRole("button", { name: "cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "submit" })).toBeDisabled();
  });
});
