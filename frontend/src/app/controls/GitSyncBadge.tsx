import { useGitConfigured } from '../gitsync'
import { activeWorkspace } from '../session'

// Page-heading badge: this workspace has a git remote, so every save commits.
export default function GitSyncBadge() {
  if (!useGitConfigured(activeWorkspace())) return null
  return (
    <span
      data-testid="git-sync-badge"
      title="Every save commits to the workspace's git remote"
      className="rounded-full border border-emerald-400/40 bg-emerald-400/10 px-2 py-0.5 text-xs font-medium text-emerald-200"
    >
      git sync
    </span>
  )
}
