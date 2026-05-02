/**
 * Vitest test setup — polyfills for jsdom environment.
 *
 * Node 20+ exposes globalThis.crypto (WebCrypto) natively, and jsdom ships
 * with TextEncoder / TextDecoder. No node: module imports are needed.
 *
 * window.matchMedia is not implemented in jsdom; Mantine requires it for its
 * colour-scheme logic. We stub it here so Mantine components can render in tests.
 */
import '@testing-library/jest-dom'

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
})
