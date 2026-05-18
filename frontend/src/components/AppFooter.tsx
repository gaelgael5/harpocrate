/**
 * AppFooter — pied de page global de l'application.
 *
 * Affiche les liens vers les pages légales (RGPD, CGU) sur toutes les vues,
 * publiques comme authentifiées. L'accessibilité permanente de ces liens
 * est requise par la politique de confidentialité et les CGU elles-mêmes
 * (acceptation tacite par poursuite d'utilisation).
 */
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import styles from "./AppFooter.module.css";

interface AppFooterProps {
  /** Variante compacte rendue dans AppShell.Footer (hauteur fixe ~36px). */
  compact?: boolean;
}

export function AppFooter({ compact = false }: AppFooterProps) {
  const { t } = useTranslation();
  const year = new Date().getFullYear();

  return (
    <footer className={compact ? styles.rootCompact : styles.root}>
      <span className={styles.brand}>Harpocrate</span>
      <span className={styles.sep} aria-hidden="true">
        ·
      </span>
      <Link to="/rgpd" className={styles.link}>
        {t("footer.rgpd")}
      </Link>
      <span className={styles.sep} aria-hidden="true">
        ·
      </span>
      <Link to="/cgu" className={styles.link}>
        {t("footer.cgu")}
      </Link>
      {!compact && <span className={styles.copy}>© {year} Harpocrate</span>}
    </footer>
  );
}
