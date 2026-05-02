/**
 * Main application layout with navbar and outlet.
 */
import { AppShell, Burger, Group, NavLink, Text, ActionIcon } from '@mantine/core'
import { useDisclosure } from '@mantine/hooks'
import { Outlet, useNavigate, NavLink as RouterNavLink } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { useCryptoStore } from '@/stores/crypto'
import { useSessionStore } from '@/stores/session'
import { logout } from '@/lib/oidc'
import { AppsMenu } from '@/components/AppsMenu'

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

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{ width: 220, breakpoint: 'sm', collapsed: { mobile: !opened } }}
      padding="md"
    >
      <AppShell.Header>
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

      <AppShell.Navbar p="xs">
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
      </AppShell.Navbar>

      <AppShell.Main>
        <Outlet />
      </AppShell.Main>
    </AppShell>
  )
}
