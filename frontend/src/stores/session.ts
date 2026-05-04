/**
 * Zustand store for OIDC session state.
 *
 * Only stores non-sensitive session metadata (user info, JWT expiry).
 * The actual OIDC token is managed by oidc-client-ts in sessionStorage
 * (it handles its own storage; we just track the decoded claims).
 *
 * For local admin login, the JWT is stored in localAdminToken (sessionStorage only).
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
  preferred_locale?: string
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
  /**
   * JWT for local admin login — stored in sessionStorage only, never persisted
   * across tabs. The api-client uses this when the OIDC token is unavailable.
   */
  localAdminToken: string | null

  setUser: (user: UserInfo) => void
  clearUser: () => void
  setAuthenticating: (v: boolean) => void
  setLocalAdminToken: (token: string | null) => void
}

// Only persist non-sensitive user metadata (no crypto, no tokens)
export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticating: false,
      localAdminToken: null,

      setUser: (user) => set({ user }),
      clearUser: () => set({ user: null, localAdminToken: null }),
      setAuthenticating: (v) => set({ isAuthenticating: v }),
      setLocalAdminToken: (token) => set({ localAdminToken: token }),
    }),
    {
      name: 'harpocrate-session',
      storage: createJSONStorage(() => sessionStorage),
      // Persiste user + localAdminToken (sessionStorage uniquement, pas localStorage).
      // Pas de crypto material persiste (rsa_priv / sym_key / wallet_keys restent en RAM).
      // Le localAdminToken survit au refresh mais pas a la fermeture de l'onglet.
      partialize: (state) => ({
        user: state.user,
        localAdminToken: state.localAdminToken,
      }),
    },
  ),
)

