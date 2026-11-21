import { create } from 'zustand'

import type { User } from '../types'

type SessionState = {
  token: string | null
  user: User | null
  setSession: (token: string, user: User) => void
  clearSession: () => void
}

export const useSessionStore = create<SessionState>((set) => ({
  // Authentication is kept in HttpOnly cookies. The token field is only an
  // in-memory marker for consumers that still use this store API.
  token: null,
  user: null,
  setSession: (_token, user) => set({ token: 'cookie-session', user }),
  clearSession: () => set({ token: null, user: null }),
}))
