/**
 * RgpdPage — politique de confidentialité / mention RGPD.
 *
 * Harpocrate stocke un minimum strict de données personnelles côté serveur
 * (email + display_name). Cette page expose, conformément aux articles 13/14
 * du RGPD, les finalités, la base légale, la durée de conservation et les
 * droits de la personne concernée.
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

export function RgpdPage() {
  const { t } = useTranslation();
  const { enabled: devMode } = useDevMode();
  const bannerOffset = devMode ? DEV_BANNER_HEIGHT : 0;

  const sections = t("rgpd.sections", { returnObjects: true }) as Section[];

  return (
    <div className={styles.root} style={{ paddingTop: 64 + bannerOffset }}>
      <div className={styles.container}>
        <Link to="/" className={styles.back}>
          {t("rgpd.back")}
        </Link>
        <div className={styles.label}>{t("rgpd.label")}</div>
        <h1 className={styles.title}>{t("rgpd.title")}</h1>
        <p className={styles.subtitle}>{t("rgpd.subtitle")}</p>

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

        <div className={styles.updated}>{t("rgpd.updated")}</div>
      </div>
    </div>
  );
}
