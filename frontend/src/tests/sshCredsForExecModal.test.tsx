import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider } from "react-i18next";
import i18n from "@/lib/i18n";

import { SshCredsForExecModal } from "@/components/SshCredsForExecModal";

function renderModal(onSubmit = vi.fn()) {
  return render(
    <MantineProvider>
      <I18nextProvider i18n={i18n}>
        <SshCredsForExecModal opened onClose={vi.fn()} onSubmit={onSubmit} />
      </I18nextProvider>
    </MantineProvider>,
  );
}

describe("SshCredsForExecModal", () => {
  it("retourne username + password sur submit en mode password", () => {
    const onSubmit = vi.fn();
    renderModal(onSubmit);
    fireEvent.change(screen.getByLabelText(/utilisateur|username/i), { target: { value: "admin" } });
    // Le SegmentedControl et le PasswordInput partagent le même label "Mot de passe" —
    // on cible l'input de type password via getAllByLabelText + filtre de type.
    const pwdInputs = screen
      .getAllByLabelText(/mot de passe|password/i)
      .filter((el) => el.tagName === "INPUT" && (el as HTMLInputElement).type !== "radio");
    fireEvent.change(pwdInputs[0]!, { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: /démarrer|start/i }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({
        username: "admin",
        auth_type: "password",
        password: "secret",
      })
    );
  });
});
