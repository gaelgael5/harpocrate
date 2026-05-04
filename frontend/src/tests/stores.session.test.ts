/**
 * Session store tests — login/logout transitions.
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { useSessionStore, type UserInfo } from '@/stores/session'

const mockUser: UserInfo = {
  id: '123e4567-e89b-12d3-a456-426614174000',
  keycloak_sub: 'sub-123',
  email: 'test@example.com',
  display_name: 'Test User',
  has_bootstrap: true,
  rsa_key_size: 2048,
  kdf_params: { memory_kb: 65536, iterations: 3, parallelism: 1 },
}

describe('useSessionStore', () => {
  beforeEach(() => {
    useSessionStore.setState({ user: null, isAuthenticating: false })
  })

  it('starts with no user', () => {
    expect(useSessionStore.getState().user).toBeNull()
  })

  it('setUser stores user info', () => {
    useSessionStore.getState().setUser(mockUser)
    expect(useSessionStore.getState().user).toEqual(mockUser)
  })

  it('clearUser removes user', () => {
    useSessionStore.getState().setUser(mockUser)
    useSessionStore.getState().clearUser()
    expect(useSessionStore.getState().user).toBeNull()
  })

  it('setAuthenticating changes flag', () => {
    useSessionStore.getState().setAuthenticating(true)
    expect(useSessionStore.getState().isAuthenticating).toBe(true)
    useSessionStore.getState().setAuthenticating(false)
    expect(useSessionStore.getState().isAuthenticating).toBe(false)
  })
})