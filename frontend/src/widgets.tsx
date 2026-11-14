// Entry of the dashboard widget bundle (vite.widgets.config.ts → /widgets.js):
// the <qv-*> tags an agent may use in dashboard HTML. Runs inside the
// sandboxed dashboard frame, never in the app. See docs/dashboard.md.

import { ParamSelect } from './core/widgets/ParamSelect'
import { defineWidget } from './core/widgets/mount'

defineWidget(
  'qv-param',
  (host) => <ParamSelect name={host.getAttribute('name') ?? ''} />,
  'inline-block',
)
