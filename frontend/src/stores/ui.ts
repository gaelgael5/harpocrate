/**
 * Zustand store for UI-level state (notifications, loading flags).
 */
import { create } from 'zustand'

interface UiState {
  /** Global loading overlay */
  isGlobalLoading: boolean
  setGlobalLoading: (v: boolean) => void
}

export const useUiStore = create<UiState>()((set) => ({
  isGlobalLoading: false,
  setGlobalLoading: (v) => set({ isGlobalLoading: v }),
}))

