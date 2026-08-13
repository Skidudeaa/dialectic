import '@testing-library/jest-dom/vitest'
import { vi } from 'vitest'

// MessageList scrolls its bottom sentinel in a layout effect. jsdom does not
// implement Element.scrollIntoView, so without this shim a component test fails
// for an environment limitation rather than for product behaviour.
Object.defineProperty(Element.prototype, 'scrollIntoView', {
  configurable: true,
  value: vi.fn(),
  writable: true,
})
