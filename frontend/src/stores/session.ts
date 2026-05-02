/**
 * Zustand store for OIDC session state.
 *
 * Only stores non-sensitive session metadata (user info, JWT expiry).
 * The actual OIDC token is managed by oidc-client-ts in sessionStorage
 * (it handles its own storage; we just track the decoded claims).
 */
import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

export interface UserInfo {
  id: string
  keycloak_sub: string
  email: string
  display_name: string | null
  has_bootstrap: boolean
  rsa_key_size: number
  kdf_params: {
    memory_kb: number
    iterations: number
    parallelism: number
  }
}

interface SessionState {
  /** Authenticated user info (null when not logged in) */
  user: UserInfo | null
  /** True when OIDC callback is being processed */
  isAuthenticating: boolean

  setUser: (user: UserInfo) => void
  clearUser: () => void
  setAuthenticating: (v: boolean) => void
}

// Only persist non-sensitive user metadata (no crypto, no tokens)
export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticating: false,

      setUser: (user) => set({ user }),
      clearUser: () => set({ user: null }),
      setAuthenticating: (v) => set({ isAuthenticating: v }),
    }),
    {
      name: 'harpocrate-session',
      storage: createJSONStorage(() => sessionStorage),
      // Only persist user metadata, never crypto material
      partialize: (state) => ({ user: state.user }),
    },
  ),
)
