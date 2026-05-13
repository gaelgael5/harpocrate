/**
 * Tests du composant ConfirmReplaceNodeModal.
 *
 * i18n : instance dédiée initialisée avec les clés FR strictement nécessaires
 * (pattern adminBackups.test.tsx).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { I18nextProvider } from "react-i18next";
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { ConfirmReplaceNodeModal } from "@/components/ConfirmReplaceNodeModal";
import type { ExistingNode } from "@/schemas/pairing";

// ─── i18n dédié ───────────────────────────────────────────────────────────────

const testI18n = i18n.createInstance();
void testI18n.use(initReactI18next).init({
  lng: "fr",
  resources: {
    fr: {
      translation: {
        "admin.replication.pairing.becomeStandby.replaceModal.title":
          "Un node existe déjà côté master",
        "admin.replication.pairing.becomeStandby.replaceModal.intro":
          "Un node de réplication portant cette URL est déjà enregistré.",
        "admin.replication.pairing.becomeStandby.replaceModal.existingLabel":
          "URL :",
        "admin.replication.pairing.becomeStandby.replaceModal.existingHost":
          "Hôte :",
        "admin.replication.pairing.becomeStandby.replaceModal.existingAppName":
          "Application name :",
        "admin.replication.pairing.becomeStandby.replaceModal.existingState":
          "Dernier état :",
        "admin.replication.pairing.becomeStandby.replaceModal.existingSeen":
          "Vu pour la dernière fois :",
        "admin.replication.pairing.becomeStandby.replaceModal.neverSeen":
          "jamais",
        "admin.replication.pairing.becomeStandby.replaceModal.cancel":
          "Annuler",
        "admin.replication.pairing.becomeStandby.replaceModal.replace":
          "Remplacer le node",
      },
    },
  },
});

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const NODE: ExistingNode = {
  id: "11111111-1111-1111-1111-111111111111",
  label: "https://b.example/",
  host: "b.example",
  application_name: "b_example",
  last_state: "disconnected",
  last_seen_at: "2026-05-10T12:00:00+00:00",
};

function renderModal(
  opened: boolean,
  onConfirm: () => void = vi.fn(),
  onCancel: () => void = vi.fn(),
) {
  return render(
    <I18nextProvider i18n={testI18n}>
      <MantineProvider>
        <ConfirmReplaceNodeModal
          opened={opened}
          existingNode={NODE}
          onConfirm={onConfirm}
          onCancel={onCancel}
          loading={false}
        />
      </MantineProvider>
    </I18nextProvider>,
  );
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe("ConfirmReplaceNodeModal", () => {
  it("affiche les détails du node existant", () => {
    renderModal(true);
    expect(screen.getByText(/https:\/\/b\.example\//)).toBeInTheDocument();
    expect(screen.getByText("b.example")).toBeInTheDocument();
    expect(screen.getByText("disconnected")).toBeInTheDocument();
  });

  it("appelle onConfirm quand on clique Remplacer", () => {
    const onConfirm = vi.fn();
    renderModal(true, onConfirm);
    fireEvent.click(screen.getByRole("button", { name: /remplacer/i }));
    expect(onConfirm).toHaveBeenCalledOnce();
  });

  it("appelle onCancel quand on clique Annuler", () => {
    const onCancel = vi.fn();
    renderModal(true, vi.fn(), onCancel);
    fireEvent.click(screen.getByRole("button", { name: /annuler/i }));
    expect(onCancel).toHaveBeenCalledOnce();
  });
});
