import { useRef, useState } from 'react'
import { downloadText, fetchExport, importYaml, type ExportKind } from '../yamlio'
import { activeWorkspace } from '../session'

type Props = {
  kind: ExportKind
  // Entity name; unused for kind="workspace" (the whole workspace exports).
  name?: string
  connType?: string
  disabled?: boolean
  // Smaller buttons for tight hosts (the workspace manage panel).
  compact?: boolean
  // Called after a successful import so the host view reloads its data.
  onImported: () => void
}

// Export / Import pair for one entity (query or dashboard) or a whole
// workspace. Export downloads the *saved* DB state as a YAML file; Import
// reads a picked YAML file and upserts whatever the file's `kind` declares.
export default function ExportImportControls({ kind, name, connType, disabled, compact, onImported }: Props) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [note, setNote] = useState('')
  const [error, setError] = useState('')
  const btnClass = compact ? 'glass-btn px-2 py-1 text-xs font-medium' : 'glass-btn px-3 py-2 font-medium'

  function flash(text: string) {
    setNote(text)
    window.setTimeout(() => setNote(''), 2500)
  }

  async function doExport() {
    setError('')
    const r = await fetchExport(kind, { name, connType, workspace: activeWorkspace() })
    if (!r.ok) {
      setError(r.message ?? 'export failed')
      return
    }
    downloadText(r.filename ?? `${kind}.yaml`, r.text ?? '')
  }

  async function doImport(file: File) {
    setError('')
    const r = await importYaml(await file.text(), activeWorkspace())
    if (!r.ok) {
      setError(r.message ?? 'import failed')
      return
    }
    flash('Imported')
    onImported()
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        data-testid="yaml-export"
        onClick={() => void doExport()}
        disabled={disabled || (kind !== 'workspace' && !name?.trim())}
        className={btnClass}
      >
        Export
      </button>
      <button
        type="button"
        data-testid="yaml-import"
        onClick={() => fileInput.current?.click()}
        disabled={disabled}
        className={btnClass}
      >
        {note || 'Import'}
      </button>
      <input
        ref={fileInput}
        data-testid="yaml-import-file"
        type="file"
        accept=".yaml,.yml,application/x-yaml"
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0]
          e.target.value = '' // allow re-picking the same file
          if (file) void doImport(file)
        }}
      />
      {error && (
        <p data-testid="yaml-error" className="text-xs text-red-300">
          {error}
        </p>
      )}
    </div>
  )
}
