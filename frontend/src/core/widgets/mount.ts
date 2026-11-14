// Registers a React component as a custom element for the dashboard frame.
// Each element renders in its own shadow root with the app's stylesheet, so
// the agent's CSS and ours cannot touch each other.

import type { ReactNode } from 'react'
import { createRoot } from 'react-dom/client'

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
    connectedCallback() {
      if (this.shadowRoot) return
      const mount = () => {
        registerProperties()
        const shadow = this.attachShadow({ mode: 'open' })
        const style = document.createElement('style')
        style.textContent = `${css}\n:host{display:${display};color-scheme:dark}`
        const root = document.createElement('div')
        shadow.append(style, root)
        createRoot(root).render(render(this))
      }
      // The bundle loads before the page's HTML, so the tag upgrades before its
      // children (the <template>s) are parsed: wait for the document.
      if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mount, { once: true })
      } else {
        mount()
      }
    }
  }
  customElements.define(tag, Widget)
}
