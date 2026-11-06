import {flushSync} from 'react-dom'

// Capture the old root at native resolution, then reveal the committed new root.
// Keeping this in the browser compositor avoids DOM copies and text resampling.
export async function revealTheme(source: HTMLElement, commit: () => void) {
  const root = document.documentElement
  const canReveal = typeof document.startViewTransition === 'function'
    && CSS.supports('clip-path', 'circle(0px at 0px 0px)')
    && !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    && document.visibilityState === 'visible'
    && source.isConnected
  if (!canReveal) {
    flushSync(commit)
    return
  }

  const rect = source.getBoundingClientRect()
  const width = window.innerWidth, height = window.innerHeight
  const x = Math.max(0, Math.min(width, rect.left + rect.width / 2))
  const y = Math.max(0, Math.min(height, rect.top + rect.height / 2))
  const radius = Math.hypot(Math.max(x, width - x), Math.max(y, height - y)) + 4
  root.style.setProperty('--theme-reveal-x', `${x}px`)
  root.style.setProperty('--theme-reveal-y', `${y}px`)
  root.style.setProperty('--theme-reveal-radius', `${radius}px`)
  root.dataset.themeReveal = 'active'

  let committed = false
  const apply = () => {
    if (committed) return
    flushSync(commit)
    committed = true
  }
  let transition: ViewTransition | undefined
  const skip = () => transition?.skipTransition()
  window.addEventListener('resize', skip)
  document.addEventListener('visibilitychange', skip)
  try {
    transition = document.startViewTransition(apply)
    // ready can reject if the window is resized, hidden or another transition
    // supersedes it. finished still waits for the theme commit and cleanup.
    await transition.ready.catch(() => {})
    await transition.finished
  } catch {
    transition?.skipTransition()
    apply()
  } finally {
    try {
      apply()
    } finally {
      window.removeEventListener('resize', skip)
      document.removeEventListener('visibilitychange', skip)
      delete root.dataset.themeReveal
      for (const key of ['x', 'y', 'radius']) root.style.removeProperty(`--theme-reveal-${key}`)
    }
  }
}
