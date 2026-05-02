/**
 * Vitest test setup — polyfills for jsdom environment.
 *
 * Node 20+ exposes globalThis.crypto (WebCrypto) natively, and jsdom ships
 * with TextEncoder / TextDecoder. No node: module imports are needed.
 */
import '@testing-library/jest-dom'
