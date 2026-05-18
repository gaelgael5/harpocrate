/**
 * CguPage — conditions générales d'utilisation.
 *
 * Document destiné à clarifier les limites de responsabilité de l'opérateur
 * du service, en particulier le fait qu'une perte de passphrase ou de phrase
 * de récupération entraîne mécaniquement la perte définitive des secrets,
 * sans recours possible côté serveur (architecture zero-knowledge).
 */
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useDevMode, DEV_BANNER_HEIGHT } from "@/hooks/useDevMode";
import styles from "./LegalPage.module.css";

interface Section {
  title: string;
  body: string;
  bullets?: string[];
}

export function CguPage() {
  const { t } = useTranslation();
  const { enabled: devMode } = useDevMode();
  const bannerOffset = devMode ? DEV_BANNER_HEIGHT : 0;

  const sections = t("cgu.sections", { returnObjects: true }) as Section[];

  return (
    <div className={styles.root} style={{ paddingTop: 64 + bannerOffset }}>
      <div className={styles.container}>
        <Link to="/" className={styles.back}>
          {t("cgu.back")}
        </Link>
        <div className={styles.label}>{t("cgu.label")}</div>
        <h1 className={styles.title}>{t("cgu.title")}</h1>
        <p className={styles.subtitle}>{t("cgu.subtitle")}</p>

        {sections.map((s) => (
          <section key={s.title} className={styles.section}>
            <h2 className={styles.sectionTitle}>{s.title}</h2>
            <p className={styles.sectionBody}>{s.body}</p>
            {s.bullets && s.bullets.length > 0 && (
              <ul className={styles.list}>
                {s.bullets.map((b) => (
                  <li key={b}>{b}</li>
                ))}
              </ul>
            )}
          </section>
        ))}

        <div className={styles.updated}>{t("cgu.updated")}</div>
      </div>
    </div>
  );
}
