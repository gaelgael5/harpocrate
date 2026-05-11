import { type ReactNode } from 'react'
import {
  AppShell,
  Burger,
  Group,
  NavLink,
  Text,
  ActionIcon,
  useMantineColorScheme,
  useComputedColorScheme,
} from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { Outlet, useNavigate, NavLink as RouterNavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useCryptoStore } from '@/stores/crypto'
import { useSessionStore } from '@/stores/session'
import { logout } from '@/lib/oidc'
import { AppsMenu } from '@/components/AppsMenu'
import { LocaleSwitcher } from '@/components/LocaleSwitcher'
import { useDevMode, DEV_BANNER_HEIGHT } from '@/hooks/useDevMode'
import { useAdminRole } from '@/hooks/useAdminRole'
import styles from './Layout.module.css'

/**
 * Layout principal de l'app authentifiée.
 *
 * Utilisable en deux modes :
 * - Comme parent-route : `<Route element={<Layout />}>...<Route .../></Route>` —
 *   les sub-routes sont rendues via `<Outlet />`.
 * - Avec children explicites : `<Layout><MaPage /></Layout>` — utile pour
 *   rendre des pages publiques avec la sidebar quand l'utilisateur est
 *   authentifié (ex : /integration accessible avant ET après login).
 */
export function Layout({ children }: { children?: ReactNode }) {
  const { t } = useTranslation()
  const [opened, { toggle }] = useDisclosure()
  const lock = useCryptoStore((s) => s.lock)
  const clearUser = useSessionStore((s) => s.clearUser)
  const navigate = useNavigate()

  async function handleLock() {
    lock()
    navigate('/unlock')
  }

  async function handleLogout() {
    lock()
    clearUser()
    await logout()
    navigate('/login')
  }

  const isAdmin = useAdminRole()
  const devMode = useDevMode()
  const offset = devMode.enabled ? DEV_BANNER_HEIGHT : 0

  const { setColorScheme } = useMantineColorScheme()
  const computedColorScheme = useComputedColorScheme('light', { getInitialValueInEffect: true })
  const isDark = computedColorScheme === 'dark'

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{ width: 220, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
      style={{ paddingTop: offset }}
    >
      <AppShell.Header className={styles.header} style={{ top: offset, height: 56 }}>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <RouterNavLink to="/wallets" className={styles.logo}>
              <span className={styles.logoMark}>Hp</span>
              Harpocrate
            </RouterNavLink>
          </Group>
          <Group gap={4}>
            <AppsMenu />
            <LocaleSwitcher />
            <ActionIcon
              variant="subtle"
              color="gray"
              onClick={() => setColorScheme(isDark ? 'light' : 'dark')}
              title={isDark ? t('nav.theme_light') : t('nav.theme_dark')}
              size="sm"
            >
              {isDark ? '☀️' : '🌙'}
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="gray"
              onClick={() => void handleLock()}
              title={t('nav.lock')}
              size="sm"
            >
              🔒
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="red"
              onClick={() => void handleLogout()}
              title={t('common.logout')}
              size="sm"
            >
              ⏻
            </ActionIcon>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar className={styles.navbar} style={{ top: offset + 56 }}>
        <NavLink component={RouterNavLink} to="/wallets"     label={t('nav.wallets')} />
        <NavLink component={RouterNavLink} to="/audit"       label={t('nav.audit')} />
        <NavLink component={RouterNavLink} to="/account"     label={t('nav.account')} />
        <NavLink component={RouterNavLink} to="/integration" label={t('nav.integration')} />
        <NavLink component={RouterNavLink} to="/api-docs" label={t('nav.api_docs')} />
        <NavLink component={RouterNavLink} to="/export-all"  label={t('nav.export_all')} />

        {isAdmin && (
          <>
            <div className={styles.divider} />
            <Text className={styles.sectionLabel}>Administration</Text>
            <NavLink component={RouterNavLink} to="/admin/system"         label={t('admin.nav_system')} />
            <NavLink component={RouterNavLink} to="/admin/backup-remotes" label={t('admin.nav_remote_backups')} />
            <NavLink component={RouterNavLink} to="/admin/backups"        label={t('admin.nav_backups')} />
            <NavLink component={RouterNavLink} to="/admin/snapshots"      label={t('admin.nav_snapshots')} />
            <NavLink component={RouterNavLink} to="/admin/replication"    label={t('admin.nav_replication')} />
            <NavLink component={RouterNavLink} to="/admin/secret-types"   label={t('admin.nav_secret_types')} />
            <NavLink component={RouterNavLink} to="/admin/users"          label={t('admin.nav_users')} />
            <NavLink component={RouterNavLink} to="/admin/anomalies"      label={t('admin.nav_anomalies')} />
            <NavLink component={RouterNavLink} to="/admin/env"            label={t('admin.nav_env')} />
          </>
        )}
      </AppShell.Navbar>

      <AppShell.Main>
        {children ?? <Outlet />}
      </AppShell.Main>
    </AppShell>
  )
}
