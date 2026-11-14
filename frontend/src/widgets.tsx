// Entry of the dashboard widget bundle (vite.widgets.config.ts → /widgets.js):
// the <qv-*> tags an agent may use in dashboard HTML. Runs inside the
// sandboxed dashboard frame, never in the app. See docs/dashboard.md.

import { parseFieldsAttr, parseOrderByAttr } from './core/dashboard/widgetChannel'
import { ParamSelect } from './core/widgets/ParamSelect'
import { SelectView } from './core/widgets/SelectView'
import { defineWidget } from './core/widgets/mount'

defineWidget(
  'qv-param',
  (host) => <ParamSelect name={host.getAttribute('name') ?? ''} />,
  'inline-block',
)

defineWidget('qv-select-view', (host) => {
  const templates: Record<string, string> = {}
  for (const t of host.querySelectorAll<HTMLTemplateElement>(':scope > template[column]')) {
    templates[t.getAttribute('column')!] = t.innerHTML
  }
  const limit = Number(host.getAttribute('limit'))
  return (
    <SelectView
      query={host.getAttribute('query') ?? ''}
      limit={Number.isInteger(limit) && limit >= 1 && limit <= 1000 ? limit : undefined}
      orderBy={parseOrderByAttr(host.getAttribute('order-by'))}
      fields={parseFieldsAttr(host.getAttribute('fields'))}
      templates={templates}
    />
  )
})
