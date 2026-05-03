import { describe, it, expect } from 'vitest'

function makeToken(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '')
  const body = btoa(JSON.stringify(payload))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=/g, '')
  return `${header}.${body}.fakesig`
}

describe('hasAdminRole', () => {
  it('returns true when realm_access.roles contains harpocrate-admin', async () => {
    const { hasAdminRole } = await import('@/hooks/useAdminRole')
    const token = makeToken({ realm_access: { roles: ['harpocrate-admin', 'user'] } })
    expect(hasAdminRole(token)).toBe(true)
  })

  it('returns false when role is absent', async () => {
    const { hasAdminRole } = await import('@/hooks/useAdminRole')
    const token = makeToken({ realm_access: { roles: ['user'] } })
    expect(hasAdminRole(token)).toBe(false)
  })

  it('returns false for an empty token', async () => {
    const { hasAdminRole } = await import('@/hooks/useAdminRole')
    expect(hasAdminRole('')).toBe(false)
  })
})
