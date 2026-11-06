const MoectPrint = (() => {
  let busy = false;
  async function print({title, description, render}) {
    if (busy) return;
    busy = true;
    const previousFocus = document.activeElement;
    const surfaces = [...document.body.children].map(element => [element, element.inert]);
    const root = document.createElement('section');
    root.id = 'moect-print-root';
    const heading = document.createElement('h1');
    heading.textContent = title;
    const summary = document.createElement('p');
    summary.className = 'print-summary';
    summary.textContent = description;
    root.append(heading, summary);
    const style = document.createElement('style');
    style.textContent = `
      #moect-print-root { display: none; }
      @page { size: A4; margin: 14mm; }
      @media print {
        body > :not(#moect-print-root) { display: none !important; }
        html, body { background: white !important; color: #111 !important; margin: 0 !important; padding: 0 !important; min-height: 0 !important; }
        #moect-print-root { display: block !important; color: #111; font-size: 11pt; }
        #moect-print-root h1 { font-size: 18pt; margin: 0 0 8pt; }
        #moect-print-root .print-summary { font-size: 9pt; color: #555; white-space: pre-wrap; margin: 0 0 18pt; }
        #moect-print-root .row, #moect-print-root .post, #moect-print-root .sticker { break-inside: avoid; }
        #moect-print-root .body { max-width: 85%; }
        #moect-print-root .bubble, #moect-print-root .card, #moect-print-root .wx-card, #moect-print-root .wx-transfer { background: white !important; color: #111 !important; box-shadow: none; border-color: #ccc !important; }
        #moect-print-root .post .body { max-width: none; }
        #moect-print-root .by, #moect-print-root .muted, #moect-print-root .system-text, #moect-print-root .post-author, #moect-print-root .quote strong { color: #555 !important; }
        #moect-print-root .attachment { max-height: 220px; }
        #moect-print-root .post { max-width: none; }
        #moect-print-root .social details { display: block; }
        #moect-print-root a { color: #333 !important; }
        #moect-print-root .reply-jump { display: none !important; }
      }`;
    try {
      surfaces.forEach(([element]) => { element.inert = true; });
      document.head.append(style);
      document.body.append(root);
      const count = await render(root);
      if (!count) throw new Error('当前筛选范围没有可打印的记录');
      summary.textContent += '\n共 ' + count + ' 条记录';
      root.querySelectorAll('details').forEach(element => { element.open = true; });
      const images = [...root.querySelectorAll('img')];
      images.forEach(image => { image.loading = 'eager'; });
      let timer;
      try {
        await Promise.race([
          Promise.allSettled([document.fonts.ready, ...images.map(image => image.decode())]),
          new Promise(resolve => { timer = setTimeout(resolve, 3000); }),
        ]);
      } finally {
        clearTimeout(timer);
      }
      window.print();
    } finally {
      root.remove();
      style.remove();
      surfaces.forEach(([element, inert]) => { element.inert = inert; });
      busy = false;
      if (previousFocus?.isConnected) previousFocus.focus({preventScroll: true});
    }
  }
  return {get busy() { return busy; }, print};
})();
