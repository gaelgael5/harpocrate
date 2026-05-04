/**
 * Typed API client for wallet export/import endpoints — LOT_07.
 *
 * exportWallet  → GET  /v1/wallets/{id}/export
 * importWallet  → POST /v1/wallets/import
 */
import { api } from '@/lib/api-client'
import {
  WalletExportSchema,
  WalletImportResponseSchema,
  type WalletExport,
  type WalletImportRequest,
  type WalletImportResponse,
} from '@/schemas/exportImport'

/**
 * Fetches the export payload for a wallet.
 * Returns the parsed WalletExport object (no values, structure only).
 */
export async function exportWallet(walletId: string): Promise<WalletExport> {
  const raw = await api.get<unknown>(`/wallets/${walletId}/export`)
  return WalletExportSchema.parse(raw)
}

/**
 * Imports a wallet from a parsed + enriched export payload.
 * The caller must supply encrypted_wallet_key_for_owner (RSA-OAEP of new wallet key).
 */
export async function importWallet(
  payload: WalletImportRequest,
): Promise<WalletImportResponse> {
  const raw = await api.post<unknown>('/wallets/import', payload)
  return WalletImportResponseSchema.parse(raw)
}
