/**
 * Parcours « Se connecter avec Harpocrate » indisponible (décision D15) : instance sans
 * Keycloak. Le compte de dépannage étant exclu du flux (D10), l'utilisateur crée l'API
 * key à la main. Aucune redirection vers l'application.
 */
import { useTranslation } from "react-i18next";

import { ConnectStatusCard } from "@/components/ConnectStatusCard";

export function ConnectUnavailablePage() {
  const { t } = useTranslation();
  return (
    <ConnectStatusCard
      title={t("connect.unavailableTitle")}
      message={t("connect.unavailableMessage")}
    />
  );
}
