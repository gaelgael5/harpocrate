/**
 * Bouton de promotion du standby en master (failover MVP).
 *
 * Auto-hide : ne s'affiche que si `GET /admin/replication/can-promote` retourne
 * `can_promote=true` (instance en mode standby). Sur master ou standalone,
 * retourne `null`.
 *
 * Click → ouvre `PromoteConfirmationModal` (double check-box anti-split-brain).
 * Submit → `POST /admin/replication/promote` → toast + invalidation des queries
 * de réplication pour que l'UI reflète le nouveau rôle.
 */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { useTranslation } from "react-i18next";

import {
  fetchCanPromote,
  promoteToMaster,
  type CanPromoteResponse,
} from "@/lib/adminApi";
import { ApiError } from "@/lib/api-client";

import { PromoteConfirmationModal } from "./PromoteConfirmationModal";

export function PromoteToMasterButton(): JSX.Element | null {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);

  const eligibility = useQuery<CanPromoteResponse>({
    queryKey: ["admin-replication-can-promote"],
    queryFn: fetchCanPromote,
    refetchInterval: 10_000,
  });

  const mutation = useMutation({
    mutationFn: () =>
      promoteToMaster({
        confirm_master_down: true,
        confirm_clients_will_be_reconfigured: true,
      }),
    onSuccess: () => {
      setModalOpen(false);
      notifications.show({
        color: "green",
        title: t("admin.replication.promote.successToast"),
        message: "",
      });
      // Le rôle de l'instance a changé : invalide toutes les queries qui
      // dépendent du mode (standby/master).
      qc.invalidateQueries({ queryKey: ["admin-replication-can-promote"] });
      qc.invalidateQueries({ queryKey: ["admin-replication-status"] });
      qc.invalidateQueries({ queryKey: ["admin-replication-strategies"] });
      qc.invalidateQueries({ queryKey: ["is-standby"] });
    },
    onError: (err: unknown) => {
      // ApiError extrait déjà `code` depuis le `detail.error` du body FastAPI
      // (cf. api-client.ts) — pas besoin de re-parser.
      const code = err instanceof ApiError ? err.code : "unknown";
      notifications.show({
        color: "red",
        title: t("admin.replication.promote.modalTitle"),
        message: t(`admin.replication.promote.errors.${code}`, {
          defaultValue: t("admin.replication.promote.errors.unknown"),
        }),
      });
    },
  });

  if (!eligibility.data?.can_promote) return null;

  return (
    <>
      <Button color="orange" onClick={() => setModalOpen(true)}>
        {t("admin.replication.promote.buttonLabel")}
      </Button>
      <PromoteConfirmationModal
        opened={modalOpen}
        masterUrl={eligibility.data?.master_url ?? null}
        onClose={() => setModalOpen(false)}
        onSubmit={() => mutation.mutate()}
        submitting={mutation.isPending}
      />
    </>
  );
}
