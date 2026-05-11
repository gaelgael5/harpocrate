/**
 * Helpers pour invalider les queries TanStack Query liées à un wallet.
 *
 * Invalider après une mutation (delete secret, delete folder, etc.) doit
 * toucher TOUTES les queries qui affichent ce wallet : compteurs (`['wallet', walletId]`),
 * arbre des dossiers à un path (`['wallet-tree', walletId, currentPath]`), liste des secrets
 * à un path (`['wallet-secrets-path', walletId, currentPath]`), arbre racine du sidebar
 * (`['wallet-tree-root', walletId]`), nœuds expandés du sidebar (`['wallet-tree-node', walletId, ...]`),
 * et le détail d'un secret (`['secret', walletId, secretId]`).
 *
 * Plutôt que d'énumérer chaque clé (et oublier la prochaine qu'on ajoutera), on
 * invalide via predicate sur le walletId.
 */
import type { QueryClient } from "@tanstack/react-query";

export async function invalidateWalletQueries(
  queryClient: QueryClient,
  walletId: string,
): Promise<void> {
  await queryClient.invalidateQueries({
    predicate: (query) =>
      query.queryKey.length >= 2 && query.queryKey[1] === walletId,
  });
}
