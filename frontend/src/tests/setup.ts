/**
 * Vitest test setup — polyfills for jsdom environment.
 *
 * Node 20+ exposes globalThis.crypto (WebCrypto) natively, and jsdom ships
 * with TextEncoder / TextDecoder. No node: module imports are needed.
 *
 * window.matchMedia is not implemented in jsdom; Mantine requires it for its
 * colour-scheme logic. We stub it here so Mantine components can render in tests.
 *
 * ResizeObserver is not implemented in jsdom; Mantine's SegmentedControl /
 * FloatingIndicator uses it internally. We stub it here so those components
 * can render without throwing.
 */
import "@testing-library/jest-dom";

Object.defineProperty(window, "matchMedia", {
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
});

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
