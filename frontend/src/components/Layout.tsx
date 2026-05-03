/**
 * Main application layout with navbar and outlet.
 */
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
import { useDevMode, DEV_BANNER_HEIGHT } from '@/hooks/useDevMode'
import { useAdminRole } from '@/hooks/useAdminRole'

export function Layout() {
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

  // Quand le bandeau dev est actif, on decale le header AppShell + on retire la
  // hauteur du bandeau de la viewport disponible. Le bandeau lui-meme est rendu
  // au niveau App.tsx en position fixed top:0.
  const devMode = useDevMode()
  const offset = devMode.enabled ? DEV_BANNER_HEIGHT : 0

  const { setColorScheme } = useMantineColorScheme()
  const computedColorScheme = useComputedColorScheme('light', { getInitialValueInEffect: true })
  const isDark = computedColorScheme === 'dark'

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 220, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
      style={{ paddingTop: offset }}
    >
      <AppShell.Header style={{ top: offset, height: 60 }}>
        <Group h="100%" px="md" justify="space-between">
          <Group>
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Text fw={700} size="lg">
              Harpocrate
            </Text>
          </Group>
          <Group>
            <AppsMenu />
            <ActionIcon
              variant="subtle"
              onClick={() => setColorScheme(isDark ? 'light' : 'dark')}
              title={isDark ? t('nav.theme_light') : t('nav.theme_dark')}
            >
              {isDark ? '☀️' : '🌙'}
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              onClick={() => void handleLock()}
              title={t('nav.lock')}
            >
              🔒
            </ActionIcon>
            <ActionIcon
              variant="subtle"
              color="red"
              onClick={() => void handleLogout()}
              title={t('common.logout')}
            >
              ⏻
            </ActionIcon>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="xs" style={{ top: offset + 60 }}>
        <NavLink
          component={RouterNavLink}
          to="/wallets"
          label={t('nav.wallets')}
        />
        <NavLink
          component={RouterNavLink}
          to="/audit"
          label={t('nav.audit')}
        />
        <NavLink
          component={RouterNavLink}
          to="/account"
          label={t('nav.account')}
        />
        <NavLink
          component={RouterNavLink}
          to="/integration"
          label={t('nav.integration')}
        />
        <NavLink
          component="a"
          href="/v1/api-docs"
          target="_blank"
          rel="noopener noreferrer"
          label={t('nav.api_docs')}
        />
        {isAdmin && (
          <NavLink label={t('nav.admin')} childrenOffset={12} defaultOpened>
            <NavLink
              component={RouterNavLink}
              to="/admin/backups"
              label={t('admin.nav_backups')}
            />
            <NavLink
              component={RouterNavLink}
              to="/admin/users"
              label={t('admin.nav_users')}
            />
            <NavLink
              component={RouterNavLink}
              to="/admin/system"
              label={t('admin.nav_system')}
            />
          </NavLink>
        )}
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
