import { useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useSessionStore } from '@/stores/session'
import { useDevMode, DEV_BANNER_HEIGHT } from '@/hooks/useDevMode'
import { LocaleSwitcher } from '@/components/LocaleSwitcher'
import styles from './LandingPage.module.css'

function CipherRing() {
  const ticks = (count: number, r: number, every = 1) =>
    Array.from({ length: count }, (_, i) => {
      const angle = (i / count) * 360
      const rad = (angle * Math.PI) / 180
      const cos = Math.cos(rad)
      const sin = Math.sin(rad)
      return (
        <line
          key={i}
          x1={200 + (r - 7) * cos}
          y1={200 + (r - 7) * sin}
          x2={200 + (r + 1) * cos}
          y2={200 + (r + 1) * sin}
          stroke="#1e40af"
          strokeWidth={i % every === 0 ? 2 : 1}
          opacity={i % every === 0 ? 0.8 : 0.2}
        />
      )
    })

  return (
    <svg className={styles.cipherRing} viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg">
      <circle cx="200" cy="200" r="188" fill="none" stroke="#1e40af" strokeWidth="0.5" opacity="0.15" />
      <circle cx="200" cy="200" r="150" fill="none" stroke="#1e40af" strokeWidth="0.4" opacity="0.1" />
      <circle cx="200" cy="200" r="112" fill="none" stroke="#1e40af" strokeWidth="0.5" opacity="0.12" />
      <circle cx="200" cy="200" r="70"  fill="none" stroke="#1e40af" strokeWidth="1"   opacity="0.08" />
      <g className={styles.rotateOuter}>{ticks(36, 188, 3)}</g>
      <g className={styles.rotateMiddle}>{ticks(24, 150, 4)}</g>
      <g className={styles.rotateInner}>{ticks(16, 112, 4)}</g>
      <g className={styles.orbitPath}>
        <circle cx="200" cy="12" r="3.5" fill="#1e40af" opacity="0.9" />
        <circle cx="200" cy="12" r="6" fill="none" stroke="#1e40af" strokeWidth="0.5" opacity="0.4" />
      </g>
      <g className={styles.orbitPath2}>
        <circle cx="200" cy="50" r="2.5" fill="#1e40af" opacity="0.7" />
      </g>
      <text
        x="200"
        y="220"
        textAnchor="middle"
        fontSize="52"
        className={styles.lockSymbol}
        fontFamily="Georgia, serif"
      >
        ⚿
      </text>
      <circle cx="200" cy="200" r="38" fill="none" stroke="#1e40af" strokeWidth="0.5" opacity="0.25" />
    </svg>
  )
}

const LockIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <rect x="3" y="11" width="18" height="11" rx="2" />
    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
  </svg>
)

const CodeIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
  </svg>
)

const FileIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="16" y1="13" x2="8" y2="13" />
    <line x1="16" y1="17" x2="8" y2="17" />
    <polyline points="10 9 9 9 8 9" />
  </svg>
)

export function LandingPage() {
  const navigate = useNavigate()
  const { t } = useTranslation()
  const user = useSessionStore((s) => s.user)
  const { enabled: devMode } = useDevMode()
  const bannerOffset = devMode ? DEV_BANNER_HEIGHT : 0

  useEffect(() => {
    if (user) navigate('/wallets', { replace: true })
  }, [user, navigate])

  const features = [
    {
      n: '01',
      icon: <LockIcon />,
      name: t('landing.features.zeroKnowledge.name'),
      desc: t('landing.features.zeroKnowledge.desc'),
      tag: t('landing.features.zeroKnowledge.tag'),
      href: undefined as string | undefined,
    },
    {
      n: '02',
      icon: <CodeIcon />,
      name: t('landing.features.devFirst.name'),
      desc: t('landing.features.devFirst.desc'),
      tag: t('landing.features.devFirst.tag'),
      href: '/integration' as string | undefined,
    },
    {
      n: '03',
      icon: <FileIcon />,
      name: t('landing.features.audit.name'),
      desc: t('landing.features.audit.desc'),
      tag: t('landing.features.audit.tag'),
      href: undefined as string | undefined,
    },
  ]

  const steps = [
    {
      n: '01',
      title: t('landing.steps.s1.title'),
      desc: t('landing.steps.s1.desc'),
      code: t('landing.steps.s1.code'),
    },
    {
      n: '02',
      title: t('landing.steps.s2.title'),
      desc: t('landing.steps.s2.desc'),
      code: t('landing.steps.s2.code'),
    },
    {
      n: '03',
      title: t('landing.steps.s3.title'),
      desc: t('landing.steps.s3.desc'),
      code: t('landing.steps.s3.code'),
    },
  ]

  return (
    <div className={styles.root}>
      {/* Nav */}
      <nav className={styles.nav} style={{ top: bannerOffset }}>
        <Link to="/" className={styles.navLogo}>
          <span className={styles.navLogoMark}>Hp</span>
          Harpocrate
        </Link>
        <div className={styles.navLinks}>
          <a href="#features" className={styles.navLink}>{t('landing.nav.features')}</a>
          <a href="#how-it-works" className={styles.navLink}>{t('landing.nav.howItWorks')}</a>
          <a href="#terminal" className={styles.navLink}>{t('landing.nav.docs')}</a>
          <LocaleSwitcher />
          <Link to="/login" className={styles.navCta}>{t('landing.nav.openVault')}</Link>
        </div>
      </nav>

      {/* Hero */}
      <section className={styles.hero} style={{ paddingTop: 80 + bannerOffset }}>
        <div className={styles.heroContent}>
          <div className={styles.heroBadge}>
            <span className={styles.heroBadgeDot} />
            {t('landing.hero.badge')}
          </div>
          <h1 className={styles.heroTitle}>
            {t('landing.hero.titleLine1')}<br />
            <span className={styles.heroTitleAccent}>{t('landing.hero.titleAccent')}</span><br />
            {t('landing.hero.titleLine3')}
          </h1>
          <p className={styles.heroSub}>{t('landing.hero.subtitle')}</p>
          <div className={styles.heroActions}>
            <Link to="/login" className={styles.btnPrimary}>{t('landing.hero.btnPrimary')}</Link>
            <a href="#how-it-works" className={styles.btnSecondary}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 8 12 12 14 14" />
              </svg>
              {t('landing.hero.btnSecondary')}
            </a>
          </div>
          <div className={styles.heroMeta}>
            <div className={styles.heroMetaItem}>
              <span className={styles.heroMetaValue}>4096</span>
              <span className={styles.heroMetaLabel}>{t('landing.hero.metaRsa')}</span>
            </div>
            <div className={styles.heroMetaItem}>
              <span className={styles.heroMetaValue}>256</span>
              <span className={styles.heroMetaLabel}>{t('landing.hero.metaAes')}</span>
            </div>
            <div className={styles.heroMetaItem}>
              <span className={styles.heroMetaValue}>0</span>
              <span className={styles.heroMetaLabel}>{t('landing.hero.metaPlaintext')}</span>
            </div>
          </div>
        </div>
        <div className={styles.heroVisual}>
          <CipherRing />
        </div>
      </section>

      {/* Features */}
      <section className={styles.features} id="features">
        <div className={styles.sectionLabel}>{t('landing.features.label')}</div>
        <h2 className={styles.sectionTitle}>
          {t('landing.features.titleLine1')}<br />
          <span className={styles.sectionTitleAccent}>{t('landing.features.titleAccent')}</span> {t('landing.features.titleLine3')}
        </h2>
        <div className={styles.featureGrid}>
          {features.map((f) => (
            <div key={f.n} className={styles.featureCard}>
              <div className={styles.featureNumber}>{f.n}</div>
              <div className={styles.featureIcon}>{f.icon}</div>
              <h3 className={styles.featureName}>{f.name}</h3>
              <p className={styles.featureDesc}>{f.desc}</p>
              <span className={styles.featureTag}>{f.tag}</span>
              {f.href && (
                <Link to={f.href} className={styles.featureLink}>
                  {t('landing.features.sdkLink')}
                </Link>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className={styles.howItWorks} id="how-it-works">
        <div className={styles.howContainer}>
          <div className={styles.sectionLabel}>{t('landing.howItWorks.label')}</div>
          <h2 className={styles.sectionTitle}>{t('landing.howItWorks.title')}</h2>
          <div className={styles.steps}>
            {steps.map((s) => (
              <div key={s.n} className={styles.step}>
                <div className={styles.stepNumber}>{s.n}</div>
                <h3 className={styles.stepTitle}>{s.title}</h3>
                <p className={styles.stepDesc}>{s.desc}</p>
                <span className={styles.stepCode}>{s.code}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Terminal */}
      <section className={styles.terminal} id="terminal">
        <div className={styles.sectionLabel}>{t('landing.terminal.label')}</div>
        <h2 className={styles.sectionTitle}>
          {t('landing.terminal.titleLine1')}<br />
          <span className={styles.sectionTitleAccent}>{t('landing.terminal.titleAccent')}</span>
        </h2>
        <div className={styles.terminalWindow}>
          <div className={styles.terminalHeader}>
            <span className={styles.terminalDot} />
            <span className={styles.terminalDot} />
            <span className={styles.terminalDot} />
            <span className={styles.terminalTitle}>harpocrate — bash</span>
          </div>
          <div className={styles.terminalBody}>
            <div className={styles.terminalLine}>
              <span className={styles.terminalPrompt}>$</span>
              <span className={styles.terminalCmd}>pip install harpocrate</span>
            </div>
            <div className={styles.terminalOut}>{t('landing.terminal.installSuccess')}</div>

            <div className={styles.terminalLine} style={{ marginTop: '0.75rem' }}>
              <span className={styles.terminalPrompt}>$</span>
              <span className={styles.terminalCmd}>
                harpocrate get{' '}
                <span className={styles.terminalFlag}>--wallet</span>{' '}
                <span className={styles.terminalStr}>production</span>{' '}
                <span className={styles.terminalFlag}>--secret</span>{' '}
                <span className={styles.terminalStr}>DATABASE_URL</span>
              </span>
            </div>
            <div className={styles.terminalOut}>{t('landing.terminal.unlocking')}</div>
            <div className={styles.terminalSuccess}>✓ postgres://user:s3cr3t@db.internal/prod</div>

            <div className={styles.terminalLine} style={{ marginTop: '0.75rem' }}>
              <span className={styles.terminalPrompt}>$</span>
              <span className={styles.terminalCmd}>
                <span className={styles.terminalComment}>{t('landing.terminal.envComment')}</span>
              </span>
            </div>
            <div className={styles.terminalLine}>
              <span className={styles.terminalPrompt}>$</span>
              <span className={styles.terminalCmd}>
                harpocrate exec{' '}
                <span className={styles.terminalFlag}>--wallet</span>{' '}
                <span className={styles.terminalStr}>production</span>
                {' -- '}
                <span className={styles.terminalStr}>node server.js</span>
              </span>
            </div>
            <div className={styles.terminalSuccess}>{t('landing.terminal.execSuccess')}</div>

            <div className={styles.terminalLine} style={{ marginTop: '0.75rem' }}>
              <span className={styles.terminalPrompt}>$</span>
              <span className={styles.terminalCmd}><span className={styles.terminalCursor} /></span>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className={styles.cta}>
        <div className={styles.ctaGlow} />
        <div className={styles.ctaContent}>
          <h2 className={styles.ctaTitle}>
            {t('landing.cta.titleLine1')}<br />
            <em style={{ color: 'var(--vault-gold)' }}>{t('landing.cta.titleAccent')}</em>?
          </h2>
          <p className={styles.ctaDesc}>{t('landing.cta.desc')}</p>
          <div className={styles.ctaActions}>
            <Link to="/login" className={styles.btnPrimary}>{t('landing.cta.button')}</Link>
          </div>
          <p className={styles.ctaMeta}>{t('landing.cta.meta')}</p>
        </div>
      </section>

      {/* Footer */}
      <footer className={styles.footer}>
        <span className={styles.footerLogo}>Harpocrate</span>
        <span className={styles.footerCopy}>{t('landing.footer.tagline')}</span>
      </footer>
    </div>
  )
}
