/**
 * PublicLayout — wrapper de toutes les routes publiques (non protégées).
 *
 * Rend l'outlet de routage suivi d'un AppFooter en bas de flux, afin que
 * les liens RGPD/CGU soient accessibles depuis n'importe quelle page,
 * y compris avant authentification.
 */
import { Outlet } from "react-router-dom";
import { AppFooter } from "@/components/AppFooter";
import styles from "./PublicLayout.module.css";

export function PublicLayout() {
  return (
    <div className={styles.shell}>
      <div className={styles.content}>
        <Outlet />
      </div>
      <AppFooter />
    </div>
  );
}
