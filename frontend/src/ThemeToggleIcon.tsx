// Hover swaps a static glyph for a looping glyph, then fades back on exit.
export function ThemeToggleIcon({dark}: {dark: boolean}) {
  const glyph = dark ? <>
    <path className="theme-icon-moon" d="M19.5 14.8A8 8 0 0 1 9.2 4.5a8 8 0 1 0 10.3 10.3Z"/>
    <path className="theme-icon-star" d="m17 3 .5 1.5L19 5l-1.5.5L17 7l-.5-1.5L15 5l1.5-.5Z"/>
    <path className="theme-icon-star theme-icon-star-small" d="M21 9v3m-1.5-1.5h3"/>
  </> : <>
    <circle className="theme-icon-sun" cx="12" cy="12" r="4"/>
    <g className="theme-icon-rays"><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.9 4.9l1.4 1.4m11.4 11.4 1.4 1.4m0-14.2-1.4 1.4M6.3 17.7l-1.4 1.4"/></g>
  </>
  return <span className="theme-toggle-icon" data-mode={dark?'dark':'light'} aria-hidden="true">
    <svg className="theme-icon-static" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{glyph}</svg>
    <svg className="theme-icon-loop" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{glyph}</svg>
  </span>
}
