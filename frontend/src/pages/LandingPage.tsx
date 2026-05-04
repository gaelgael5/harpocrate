import { useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useSessionStore } from '@/stores/session'
import { useDevMode, DEV_BANNER_HEIGHT } from '@/hooks/useDevMode'
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
      {/* Static rings */}
      <circle cx="200" cy="200" r="188" fill="none" stroke="#1e40af" strokeWidth="0.5" opacity="0.15" />
      <circle cx="200" cy="200" r="150" fill="none" stroke="#1e40af" strokeWidth="0.4" opacity="0.1" />
      <circle cx="200" cy="200" r="112" fill="none" stroke="#1e40af" strokeWidth="0.5" opacity="0.12" />
      <circle cx="200" cy="200" r="70"  fill="none" stroke="#1e40af" strokeWidth="1"   opacity="0.08" />

      {/* Outer rotating ticks */}
      <g className={styles.rotateOuter}>{ticks(36, 188, 3)}</g>

      {/* Middle counter-rotating ticks */}
      <g className={styles.rotateMiddle}>{ticks(24, 150, 4)}</g>

      {/* Inner rotating ticks */}
      <g className={styles.rotateInner}>{ticks(16, 112, 4)}</g>

      {/* Orbit dot on outer ring */}
      <g className={styles.orbitPath}>
        <circle cx="200" cy="12" r="3.5" fill="#1e40af" opacity="0.9" />
        <circle cx="200" cy="12" r="6" fill="none" stroke="#1e40af" strokeWidth="0.5" opacity="0.4" />
      </g>

      {/* Orbit dot on middle ring */}
      <g className={styles.orbitPath2}>
        <circle cx="200" cy="50" r="2.5" fill="#1e40af" opacity="0.7" />
      </g>

      {/* Center lock glyph */}
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

const FEATURES = [
  {
    n: '01',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="3" y="11" width="18" height="11" rx="2" />
        <path d="M7 11V7a5 5 0 0 1 10 0v4" />
      </svg>
    ),
    name: 'Zero Knowledge',
    desc: 'Encryption happens in your browser via WebCrypto API and Argon2id. The server stores only ciphertext — your secrets are mathematically inaccessible to us.',
    tag: 'AES-256-GCM · RSA-OAEP · Argon2id',
    href: undefined as string | undefined,
  },
  {
    n: '02',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <polyline points="16 18 22 12 16 6" />
        <polyline points="8 6 2 12 8 18" />
      </svg>
    ),
    name: 'Developer First',
    desc: 'Native CLI, Python SDK, and REST API with bearer tokens. Pull secrets directly into CI pipelines without storing credentials in environment files.',
    tag: 'hrpv_* tokens · Python · bash',
    href: '/integration',
  },
  {
    n: '03',
    icon: (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
        <polyline points="14 2 14 8 20 8" />
        <line x1="16" y1="13" x2="8" y2="13" />
        <line x1="16" y1="17" x2="8" y2="17" />
        <polyline points="10 9 9 9 8 9" />
      </svg>
    ),
    name: 'Audit Everything',
    desc: 'Immutable audit log streams every read, write, grant, and revocation to Loki. Know exactly who accessed what, from which IP, at what time.',
    tag: 'Loki · Grafana · structured logs',
    href: undefined as string | undefined,
  },
]

const STEPS = [
  {
    n: '01',
    title: 'Generate your keypair',
    desc: 'On first login, a 4096-bit RSA keypair is generated entirely in your browser. Your private key is encrypted with your passphrase via Argon2id — it never leaves your device in cleartext.',
    code: 'Argon2id → AES-GCM wrapping → RSA-4096',
  },
  {
    n: '02',
    title: 'Encrypt secrets locally',
    desc: 'Each wallet holds a symmetric AES-256 key, itself encrypted with your public key. Secret values are encrypted client-side before upload. The server receives only opaque blobs.',
    code: 'plaintext → AES-GCM(wallet_key) → server',
  },
  {
    n: '03',
    title: 'Share with precision',
    desc: 'Grant colleagues access using a five-bit permission bitmap: READ, WRITE, ADD, REMOVE, INIT. Their public key encrypts the wallet key — access is cryptographically scoped.',
    code: 'wallet_key → RSA-OAEP(recipient.pub)',
  },
]

export function LandingPage() {
  const navigate = useNavigate()
  const user = useSessionStore((s) => s.user)
  const { enabled: devMode } = useDevMode()
  const bannerOffset = devMode ? DEV_BANNER_HEIGHT : 0

  useEffect(() => {
    if (user) navigate('/wallets', { replace: true })
  }, [user, navigate])

  return (
    <div className={styles.root}>
      {/* Nav */}
      <nav className={styles.nav} style={{ top: bannerOffset }}>
        <Link to="/" className={styles.navLogo}>
          <span className={styles.navLogoMark}>Hp</span>
          Harpocrate
        </Link>
        <div className={styles.navLinks}>
          <a href="#features" className={styles.navLink}>Features</a>
          <a href="#how-it-works" className={styles.navLink}>How it works</a>
          <a href="#terminal" className={styles.navLink}>Docs</a>
          <Link to="/login" className={styles.navCta}>Open vault →</Link>
        </div>
      </nav>

      {/* Hero */}
      <section className={styles.hero} style={{ paddingTop: 80 + bannerOffset }}>
        <div className={styles.heroContent}>
          <div className={styles.heroBadge}>
            <span className={styles.heroBadgeDot} />
            End-to-end zero-knowledge
          </div>
          <h1 className={styles.heroTitle}>
            Your secrets,<br />
            <span className={styles.heroTitleAccent}>mathematically</span><br />
            out of reach.
          </h1>
          <p className={styles.heroSub}>
            A secrets manager where even the server operator cannot read your data.
            Cryptography runs entirely in your browser — the server stores only encrypted blobs.
          </p>
          <div className={styles.heroActions}>
            <Link to="/login" className={styles.btnPrimary}>Open your vault</Link>
            <a href="#how-it-works" className={styles.btnSecondary}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <polyline points="12 8 12 12 14 14" />
              </svg>
              See how it works
            </a>
          </div>
          <div className={styles.heroMeta}>
            <div className={styles.heroMetaItem}>
              <span className={styles.heroMetaValue}>4096</span>
              <span className={styles.heroMetaLabel}>RSA key bits</span>
            </div>
            <div className={styles.heroMetaItem}>
              <span className={styles.heroMetaValue}>256</span>
              <span className={styles.heroMetaLabel}>AES key bits</span>
            </div>
            <div className={styles.heroMetaItem}>
              <span className={styles.heroMetaValue}>0</span>
              <span className={styles.heroMetaLabel}>Plaintext on server</span>
            </div>
          </div>
        </div>
        <div className={styles.heroVisual}>
          <CipherRing />
        </div>
      </section>

      {/* Features */}
      <section className={styles.features} id="features">
        <div className={styles.sectionLabel}>Core guarantees</div>
        <h2 className={styles.sectionTitle}>
          Built for teams who<br />
          <span className={styles.sectionTitleAccent}>cannot afford to trust</span> the server.
        </h2>
        <div className={styles.featureGrid}>
          {FEATURES.map((f) => (
            <div key={f.n} className={styles.featureCard}>
              <div className={styles.featureNumber}>{f.n}</div>
              <div className={styles.featureIcon}>{f.icon}</div>
              <h3 className={styles.featureName}>{f.name}</h3>
              <p className={styles.featureDesc}>{f.desc}</p>
              <span className={styles.featureTag}>{f.tag}</span>
              {f.href && (
                <Link to={f.href} className={styles.featureLink}>
                  SDK &amp; API docs →
                </Link>
              )}
            </div>
          ))}
        </div>
      </section>

      {/* How it works */}
      <section className={styles.howItWorks} id="how-it-works">
        <div className={styles.howContainer}>
          <div className={styles.sectionLabel}>The protocol</div>
          <h2 className={styles.sectionTitle}>
            Three steps, zero trust.
          </h2>
          <div className={styles.steps}>
            {STEPS.map((s) => (
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
        <div className={styles.sectionLabel}>Developer workflow</div>
        <h2 className={styles.sectionTitle}>
          Secrets in your pipeline,<br />
          <span className={styles.sectionTitleAccent}>not in your config files.</span>
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
            <div className={styles.terminalOut}>Successfully installed harpocrate-0.1.0</div>

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
            <div className={styles.terminalOut}>🔑 Unlocking wallet… decrypting locally…</div>
            <div className={styles.terminalSuccess}>✓ postgres://user:s3cr3t@db.internal/prod</div>

            <div className={styles.terminalLine} style={{ marginTop: '0.75rem' }}>
              <span className={styles.terminalPrompt}>$</span>
              <span className={styles.terminalCmd}>
                <span className={styles.terminalComment}># Or inject into your process environment</span>
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
            <div className={styles.terminalSuccess}>✓ 12 secrets injected · server listening on :3000</div>

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
            Ready to keep your<br />
            <em style={{ color: 'var(--vault-gold)' }}>secrets secret</em>?
          </h2>
          <p className={styles.ctaDesc}>
            Self-host in minutes. No subscription. No telemetry.
            Your data never touches our servers — because we don't have any.
          </p>
          <div className={styles.ctaActions}>
            <Link to="/login" className={styles.btnPrimary}>Open your vault</Link>
          </div>
          <p className={styles.ctaMeta}>Open source · Self-hosted · Zero knowledge</p>
        </div>
      </section>

      {/* Footer */}
      <footer className={styles.footer}>
        <span className={styles.footerLogo}>Harpocrate</span>
        <span className={styles.footerCopy}>
          The god of silence keeps your secrets.
        </span>
      </footer>
    </div>
  )
}
