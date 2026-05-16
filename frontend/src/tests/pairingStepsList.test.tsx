/**
 * Tests du composant PairingStepsList.
 *
 * i18n mocké : t(key) → dernier segment de la clé.
 * Exemples :
 *   'admin.replication.pairing.wizard.back'     → 'back'
 *   'admin.replication.pairing.wizard.markDone' → 'markDone'
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MantineProvider } from '@mantine/core'
import React from 'react'

import { PairingStepsList } from '@/components/PairingStepsList'

// ─── i18n mock ────────────────────────────────────────────────────────────────
vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const parts = key.split('.')
      return parts[parts.length - 1] ?? key
    },
    i18n: { language: 'fr', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: React.ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: vi.fn() },
}))

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const STEPS = [
  { idx: 0, title: 'Stop pg', command: 'docker stop x' },
  { idx: 1, title: 'Backup', command: 'pg_basebackup …' },
]

function renderComponent(ui: React.ReactNode) {
  return render(
    <MantineProvider>{ui}</MantineProvider>,
  )
}

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('PairingStepsList', () => {
  it('shows the active step command and disables Back at idx 0', () => {
    renderComponent(
      <PairingStepsList
        steps={STEPS}
        currentIdx={0}
        onDone={vi.fn()}
        onBack={vi.fn()}
      />,
    )
    // The command is rendered inside <Code> block
    expect(screen.getByText('docker stop x')).toBeInTheDocument()
    // t('admin.replication.pairing.wizard.back') → 'back'
    const backBtn = screen.getByRole('button', { name: /^back$/i })
    expect(backBtn).toBeDisabled()
  })

  it('calls onDone with current idx when markDone clicked', () => {
    const onDone = vi.fn()
    renderComponent(
      <PairingStepsList
        steps={STEPS}
        currentIdx={0}
        onDone={onDone}
        onBack={vi.fn()}
      />,
    )
    // t('admin.replication.pairing.wizard.markDone') → 'markDone'
    fireEvent.click(screen.getByRole('button', { name: /^markDone$/i }))
    expect(onDone).toHaveBeenCalledWith(0)
  })

  it('calls onBack with current idx', () => {
    const onBack = vi.fn()
    renderComponent(
      <PairingStepsList
        steps={STEPS}
        currentIdx={1}
        onDone={vi.fn()}
        onBack={onBack}
      />,
    )
    // At idx=1, back button is enabled
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }))
    expect(onBack).toHaveBeenCalledWith(1)
  })
})
