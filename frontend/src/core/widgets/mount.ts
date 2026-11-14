// Registers a React component as a custom element for the dashboard frame.
// Each element renders in its own shadow root with the app's stylesheet, so
// the agent's CSS and ours cannot touch each other.

import type { ReactNode } from 'react'
import { createRoot, type Root } from 'react-dom/client'

import css from '../../index.css?inline'

// Tailwind registers its --tw-* defaults with @property, which a browser
// ignores inside a shadow root: register them once on the document instead.
// They only declare custom properties, so the agent's page is unaffected.
function registerProperties(): void {
  if (document.getElementById('qv-properties')) return
  const style = document.createElement('style')
  style.id = 'qv-properties'
  style.textContent = (css.match(/@property[^{]+\{[^}]*\}/g) ?? []).join('\n')
  document.head.append(style)
}

export function defineWidget(
  tag: string,
  render: (host: HTMLElement) => ReactNode,
  display: 'block' | 'inline-block' = 'block',
): void {
  class Widget extends HTMLElement {
    private root: Root | null = null
    private queued = false
    connectedCallback() {
      if (this.root || this.queued) return
      this.queued = true
      const mount = () => {
        this.queued = false
        if (!this.isConnected) return
        registerProperties()
        // Re-attached after a removal: the shadow root is still there.
        const shadow = this.shadowRoot ?? this.attachShadow({ mode: 'open' })
        const style = document.createElement('style')
        style.textContent = `${css}\n:host{display:${display};color-scheme:dark}`
        const el = document.createElement('div')
        shadow.replaceChildren(style, el)
        this.root = createRoot(el)
        this.root.render(render(this))
      }
      // The bundle loads before the page's HTML, so the tag upgrades before its
      // children (the <template>s) are parsed: wait for the document.
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount, { once: true })
      } else {
        mount()
      }
    }
    // A page that re-renders its HTML must not leave the old widget querying.
    disconnectedCallback() {
      this.root?.unmount()
      this.root = null
    }
  }
  customElements.define(tag, Widget)
}
