// Shared by the desktop frontend and portable offline HTML. No native selects.
(() => {
  if (customElements.get('moect-date-range')) return;
  const pad = n => String(n).padStart(2, '0');
  const day = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const valid = v => /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(v) && !isNaN(Date.parse(v));
  const chevron = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="m4 6 4 4 4-4"/></svg>';
  const css = `
    :host{display:inline-block;max-width:100%;font:inherit;color:inherit;--bg:var(--popover,#fff);--fg:var(--popover-foreground,#30283c);--line:var(--border,#e6dfed);--accent:var(--primary,#8163cb);--on-accent:var(--primary-foreground,#fff);--soft:color-mix(in srgb,var(--accent) 9%,var(--bg));--dim:color-mix(in srgb,var(--fg) 56%,var(--bg))}
    *{box-sizing:border-box;scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--accent) 45%,var(--bg)) transparent}
    ::-webkit-scrollbar{width:5px;height:5px}::-webkit-scrollbar-track{background:transparent}::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--accent) 45%,var(--bg));border-radius:20px}
    button{font:inherit;color:inherit;cursor:pointer;border:0;background:none}button:disabled{opacity:.4;cursor:default}button:focus-visible{outline:2px solid var(--accent);outline-offset:2px}svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:1.6;stroke-linecap:round;stroke-linejoin:round}[hidden]{display:none!important}
    .trigger{display:inline-flex;gap:9px;align-items:center;width:fit-content;max-width:min(100%,360px);min-height:36px;padding:8px 15px;border-radius:20px;background:color-mix(in srgb,var(--fg) 5%,transparent);text-align:left;font-size:13px;line-height:1.5}.caption{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
    dialog{position:fixed;inset:auto;margin:0;padding:0;max-width:calc(100vw - 24px);max-height:calc(100vh - 24px);overflow:auto;border:1px solid var(--line);border-radius:18px;background:var(--bg);color:var(--fg);box-shadow:0 18px 64px #0002;font:inherit}
    dialog::backdrop{background:var(--moect-backdrop,rgba(0,0,0,.25))}.panel{position:relative;display:flex;width:540px;max-width:100%;min-height:360px}
    .calendar{padding:18px;width:300px;flex-shrink:0}.month{display:grid;grid-template-columns:28px minmax(0,1fr) 28px;align-items:center;margin-bottom:16px;height:34px}.month-center{display:flex;align-items:center;justify-content:center;gap:7px;min-width:0}.month button{display:flex;align-items:center;justify-content:center;gap:5px;border-radius:10px;height:32px;font-size:14px;font-weight:500}.month .year,.month .mon{padding:0 10px;background:var(--soft);white-space:nowrap}.month .prev,.month .next{padding:0;font-size:23px;color:var(--dim)}.month button:hover{background:color-mix(in srgb,var(--accent) 16%,var(--bg));color:var(--accent)}
    .week,.days{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));text-align:center;gap:3px}.week{color:var(--dim);font-size:12px;margin-bottom:8px}.day{height:34px;border-radius:10px;padding:0;font-size:13px;font-variant-numeric:tabular-nums}.day:hover,.between{background:var(--soft)}.edge{background:var(--accent)!important;color:var(--on-accent)}.today{box-shadow:inset 0 0 0 1px var(--line)}
    aside{width:240px;padding:20px;border-left:1px solid var(--line);display:flex;flex-direction:column;gap:12px}.label{font-size:11px;color:var(--dim);margin-bottom:6px}.date{font-size:14px;font-variant-numeric:tabular-nums;margin-bottom:9px}.endpoint+.endpoint{margin-top:18px}.clock{display:flex;align-items:center;gap:7px}.time-part{display:flex;align-items:center;justify-content:center;gap:9px;min-width:78px;height:36px;border:1px solid var(--line);border-radius:11px;background:var(--soft);font-size:15px;font-variant-numeric:tabular-nums}.time-part small{font-size:10px;color:var(--dim);font-weight:400}.time-part:hover:not(:disabled),.time-part[aria-expanded=true]{border-color:var(--accent);color:var(--accent)}.colon{color:var(--dim)}
    .actions{margin-top:auto;display:grid;grid-template-columns:1fr 1fr;gap:8px}.actions button{height:32px;border-radius:18px;font-size:12px}.actions .apply{grid-column:1/-1;background:var(--accent);color:var(--on-accent);height:35px}.actions .cancel{grid-column:1/-1;border:1px solid var(--line)}.quiet{color:var(--dim)}.quiet:hover{color:var(--accent);background:var(--soft)}.error{color:#c54848;font-size:11px;min-height:16px}
    .flyout{position:absolute;z-index:5;width:232px;padding:12px;border:1px solid var(--line);border-radius:15px;background:var(--bg);box-shadow:0 12px 36px #0002}.flyout-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;font-size:12px;color:var(--dim)}.flyout-close{width:24px;height:24px;border-radius:8px;font-size:17px}.flyout-close:hover{color:var(--accent);background:var(--soft)}.option-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:5px;max-height:190px;overflow:auto;padding:2px}.option-grid.years{grid-template-columns:repeat(4,minmax(0,1fr))}.option{height:32px;border-radius:9px;font-size:12px;font-variant-numeric:tabular-nums;flex-shrink:0}.option:hover{background:var(--soft);color:var(--accent)}.option[aria-selected=true]{background:var(--accent);color:var(--on-accent);font-weight:500}
    .time-columns{display:grid;grid-template-columns:1fr 1fr;gap:9px}.column-label{text-align:center;font-size:11px;color:var(--dim);margin:0 0 6px}.time-list{height:174px;overflow:auto;display:flex;flex-direction:column;gap:3px;padding:3px;border-radius:11px;background:var(--soft);overscroll-behavior:contain}.time-list .option{width:100%;height:31px;font-size:14px}.flyout-actions{display:flex;gap:7px;margin-top:11px}.flyout-actions button{flex:1;height:31px;border-radius:17px;font-size:12px}.time-apply{background:var(--accent);color:var(--on-accent)}.time-cancel{border:1px solid var(--line)}
    @media(max-width:560px){.panel{flex-direction:column;width:300px}.calendar,aside{width:100%}aside{border-left:0;border-top:1px solid var(--line);gap:8px;padding:16px}.endpoints{display:grid;grid-template-columns:1fr 1fr;gap:16px}.endpoint+.endpoint{margin-top:0}.clock{gap:4px}.time-part{min-width:53px;padding:0 5px;gap:4px}.actions .cancel{grid-column:2}.actions .apply{grid-column:1}.flyout{width:232px}}
  `;

  class DateRange extends HTMLElement {
    static get observedAttributes() { return ['start', 'end', 'empty-label', 'disabled']; }
    constructor() { super(); this.attachShadow({mode: 'open'}); this.month = new Date(); this.s = ''; this.e = ''; this.stage = 0; this.menu = null; }
    connectedCallback() { this.render(); }
    attributeChangedCallback() { if (this.isConnected) this.render(); }
    q(selector) { return this.shadowRoot.querySelector(selector); }
    modal(open) { this.dispatchEvent(new CustomEvent('moect-calendar-modal', {detail: {open}, bubbles: true, composed: true})); }
    render() {
      if (this.q('dialog[open]')) return;
      this.shadowRoot.innerHTML = `<style>${css}</style><button class="trigger" type="button" aria-haspopup="dialog"><span aria-hidden="true">▦</span><span class="caption"></span></button><dialog aria-label="选择时间范围（北京时间）"><div class="panel"><div class="calendar"><div class="month"><button class="prev" aria-label="上个月">‹</button><div class="month-center"><button class="year" aria-label="选择年份" aria-haspopup="dialog"><span></span>${chevron}</button><button class="mon" aria-label="选择月份" aria-haspopup="dialog"><span></span>${chevron}</button></div><button class="next" aria-label="下个月">›</button></div><div class="week">${['日','一','二','三','四','五','六'].map(v => `<span>${v}</span>`).join('')}</div><div class="days"></div></div><aside><div class="endpoints"></div><div class="error" role="status"></div><div class="actions"><button class="today-button quiet">回到今天</button><button class="clear quiet">清除</button><button class="apply">应用并确定</button><button class="cancel">取消</button></div></aside><div class="flyout" hidden role="dialog" aria-modal="false"></div></div></dialog>`;
      for (const button of this.shadowRoot.querySelectorAll('button')) button.type = 'button';
      const s = this.getAttribute('start') || '', e = this.getAttribute('end') || '', dialog = this.q('dialog'), trigger = this.q('.trigger');
      this.q('.caption').textContent = valid(s) ? `${s.replace('T',' ')}${valid(e) ? ' 至 ' + e.replace('T',' ') : ''}` : (this.getAttribute('empty-label') || '选择时间范围（留空显示全部）');
      trigger.title = this.q('.caption').textContent;
      trigger.disabled = this.hasAttribute('disabled');
      trigger.onclick = () => {
        this.s = s; this.e = e; this.stage = 0; this.month = valid(s) ? new Date(s) : new Date(); this.fill();
        dialog.showModal(); this.modal(true);
        const r = trigger.getBoundingClientRect();
        dialog.style.left = Math.max(12, Math.min(r.left, innerWidth - dialog.offsetWidth - 12)) + 'px';
        dialog.style.top = Math.max(12, Math.min(r.bottom + 8, innerHeight - dialog.offsetHeight - 12)) + 'px';
      };
      this.q('.prev').onclick = () => { this.closeMenu(); this.month = new Date(this.month.getFullYear(), this.month.getMonth() - 1, 1); this.fill(); };
      this.q('.next').onclick = () => { this.closeMenu(); this.month = new Date(this.month.getFullYear(), this.month.getMonth() + 1, 1); this.fill(); };
      this.q('.year').onclick = event => this.openMenu('year', event.currentTarget);
      this.q('.mon').onclick = event => this.openMenu('month', event.currentTarget);
      this.q('.today-button').onclick = () => { this.closeMenu(); const d = day(new Date()); this.month = new Date(); this.s = d + 'T00:00'; this.e = d + 'T23:59'; this.stage = 0; this.fill(); };
      this.q('.cancel').onclick = () => dialog.close();
      this.q('.clear').onclick = () => this.commit('', '');
      this.q('.apply').onclick = () => { if (this.valid()) this.commit(this.s, this.e); };
      dialog.addEventListener('close', () => { this.closeMenu(); this.modal(false); });
      dialog.addEventListener('cancel', event => { if (this.menu) { event.preventDefault(); this.closeMenu(true); } });
      dialog.addEventListener('keydown', event => { if (event.key === 'Escape' && this.menu) { event.preventDefault(); event.stopPropagation(); this.closeMenu(true); } });
      dialog.addEventListener('click', event => {
        const r = dialog.getBoundingClientRect();
        if (event.target === dialog && (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom)) dialog.close();
        else if (this.menu && !this.q('.flyout').contains(event.target) && event.target !== this.menu.anchor && !this.menu.anchor.contains(event.target)) this.closeMenu();
      });
    }
    commit(start, end) {
      this.q('dialog').close(); this.setAttribute('start', start); this.setAttribute('end', end);
      this.dispatchEvent(new CustomEvent('range-change', {detail: {start, end}, bubbles: true, composed: true}));
    }
    valid() { return valid(this.s) && valid(this.e) && this.s <= this.e; }
    validate() { this.q('.apply').disabled = !this.valid(); this.q('.error').textContent = this.s > this.e ? '结束时间不能早于开始时间' : ''; }
    button(text, className, action) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = text; button.className = className; button.onclick = action; return button;
    }
    closeMenu(focus = false) {
      const anchor = this.menu?.anchor; this.menu = null;
      const flyout = this.q('.flyout'); if (flyout) { flyout.hidden = true; flyout.replaceChildren(); }
      if (anchor) { anchor.setAttribute('aria-expanded', 'false'); if (focus && anchor.isConnected) anchor.focus(); }
    }
    openMenu(type, anchor, key = '', part = 0) {
      if (this.menu?.anchor === anchor) { this.closeMenu(true); return; }
      this.closeMenu(); this.menu = {type, anchor, key}; anchor.setAttribute('aria-expanded', 'true');
      const flyout = this.q('.flyout'); flyout.hidden = false; flyout.replaceChildren();
      const label = type === 'year' ? '选择年份' : type === 'month' ? '选择月份' : (key === 's' ? '开始时间' : '结束时间');
      flyout.setAttribute('aria-label', label);
      const heading = document.createElement('div'); heading.className = 'flyout-head'; heading.textContent = label;
      const close = this.button('×', 'flyout-close', () => this.closeMenu(true)); close.setAttribute('aria-label', '关闭选择面板'); heading.append(close); flyout.append(heading);
      if (type === 'time') this.timeMenu(flyout, key, part);
      else {
        const grid = document.createElement('div'); grid.className = 'option-grid' + (type === 'year' ? ' years' : ''); grid.setAttribute('role', 'listbox'); grid.setAttribute('aria-label', label);
        const first = type === 'year' ? Math.min(2005, this.month.getFullYear()) : 0;
        const last = type === 'year' ? Math.max(new Date().getFullYear(), this.month.getFullYear()) : 11;
        const selected = type === 'year' ? this.month.getFullYear() : this.month.getMonth();
        for (let value = first; value <= last; value++) {
          const button = this.button(type === 'year' ? String(value) : `${value + 1}月`, 'option', () => {
            this.month = type === 'year' ? new Date(value, this.month.getMonth(), 1) : new Date(this.month.getFullYear(), value, 1);
            this.closeMenu(); this.fill(); anchor.focus();
          });
          button.setAttribute('role', 'option'); button.setAttribute('aria-selected', String(value === selected)); grid.append(button);
        }
        this.listKeys(grid, type === 'year' ? 4 : 3); flyout.append(grid);
      }
      const panel = this.q('.panel'), a = anchor.getBoundingClientRect(), p = panel.getBoundingClientRect();
      flyout.style.left = Math.max(8, Math.min(a.left - p.left, panel.clientWidth - flyout.offsetWidth - 8)) + 'px';
      flyout.style.top = Math.max(8, Math.min(a.bottom - p.top + 6, panel.clientHeight - flyout.offsetHeight - 8)) + 'px';
      requestAnimationFrame(() => {
        if (!this.menu || this.menu.anchor !== anchor) return;
        const target = type === 'time' ? flyout.querySelectorAll('.time-list')[part]?.querySelector('[aria-selected="true"]') : flyout.querySelector('[aria-selected="true"]');
        if (type === 'time') for (const list of flyout.querySelectorAll('.time-list')) list.querySelector('[aria-selected="true"]')?.scrollIntoView({block: 'center'});
        target?.focus({preventScroll: true}); if (type !== 'time') target?.scrollIntoView({block: 'nearest'});
      });
    }
    listKeys(list, columns = 1) {
      const options = [...list.querySelectorAll('[role="option"]')];
      for (const option of options) {
        option.tabIndex = option.getAttribute('aria-selected') === 'true' ? 0 : -1;
        option.addEventListener('focus', () => { for (const other of options) other.tabIndex = other === option ? 0 : -1; });
      }
      list.addEventListener('keydown', event => {
        const buttons = [...list.querySelectorAll('[role="option"]')], index = buttons.indexOf(this.shadowRoot.activeElement); if (index < 0) return;
        let next = index;
        if (event.key === 'ArrowDown') next += columns; else if (event.key === 'ArrowUp') next -= columns;
        else if (event.key === 'ArrowRight') next++; else if (event.key === 'ArrowLeft') next--;
        else if (event.key === 'Home') next = 0; else if (event.key === 'End') next = buttons.length - 1; else return;
        event.preventDefault(); buttons[Math.max(0, Math.min(next, buttons.length - 1))].focus();
      });
    }
    timeMenu(flyout, key, focusedPart) {
      const pieces = this[key].slice(11).split(':');
      const columns = document.createElement('div'); columns.className = 'time-columns';
      for (let part = 0; part < 2; part++) {
        const column = document.createElement('div'), label = document.createElement('div'), list = document.createElement('div');
        label.className = 'column-label'; label.textContent = part ? '分钟' : '小时'; list.className = 'time-list'; list.setAttribute('role', 'listbox'); list.setAttribute('aria-label', label.textContent);
        for (let value = 0; value < (part ? 60 : 24); value++) {
          const button = this.button(pad(value), 'option', () => {
            pieces[part] = pad(value);
            for (const option of list.children) option.setAttribute('aria-selected', String(option === button));
          });
          button.setAttribute('role', 'option'); button.setAttribute('aria-selected', String(pieces[part] === pad(value))); list.append(button);
        }
        this.listKeys(list); column.append(label, list); columns.append(column);
      }
      const actions = document.createElement('div'); actions.className = 'flyout-actions';
      actions.append(this.button('取消', 'time-cancel', () => this.closeMenu(true)), this.button('确定时间', 'time-apply', () => {
        const anchor = this.menu?.anchor; this[key] = this[key].slice(0, 10) + 'T' + pieces.join(':'); this.closeMenu(); this.fill();
        this.q(`[data-clock="${key}-${focusedPart}"]`)?.focus(); if (anchor) anchor.setAttribute('aria-expanded', 'false');
      }));
      flyout.append(columns, actions);
    }
    fill() {
      const year = this.month.getFullYear(), month = this.month.getMonth();
      this.q('.year span').textContent = year; this.q('.mon span').textContent = `${month + 1}月`;
      const days = this.q('.days'); days.replaceChildren();
      for (let i = 0; i < new Date(year, month, 1).getDay(); i++) days.append(document.createElement('span'));
      for (let n = 1; n <= new Date(year, month + 1, 0).getDate(); n++) {
        const value = day(new Date(year, month, n)), s = this.s.slice(0, 10), e = this.e.slice(0, 10);
        const button = this.button(n, 'day' + (value === s || value === e ? ' edge' : value > s && value < e ? ' between' : '') + (value === day(new Date()) ? ' today' : ''), () => {
          this.closeMenu();
          if (!this.stage) { this.s = value + 'T' + (this.s.slice(11) || '00:00'); this.e = value + 'T' + (this.e.slice(11) || '23:59'); this.stage = 1; }
          else { if (value < this.s.slice(0,10)) { const previous = this.s.slice(0,10); this.s = value + 'T' + this.s.slice(11); this.e = previous + 'T' + this.e.slice(11); } else this.e = value + 'T' + this.e.slice(11); this.stage = 0; }
          this.fill();
        });
        button.setAttribute('aria-label', value); days.append(button);
      }
      const endpoints = this.q('.endpoints'); endpoints.replaceChildren();
      for (const [key, label, fallback] of [['s', '开始', '00:00'], ['e', '结束', '23:59']]) {
        const wrap = document.createElement('div'), title = document.createElement('div'), date = document.createElement('div'), clock = document.createElement('div');
        wrap.className = 'endpoint'; title.className = 'label'; title.textContent = label; date.className = 'date'; date.textContent = this[key].slice(0,10).replaceAll('-', '/') || '请选择日期'; clock.className = 'clock';
        const current = this[key].slice(11) || fallback;
        for (let part = 0; part < 2; part++) {
          if (part) { const colon = document.createElement('span'); colon.className = 'colon'; colon.textContent = ':'; clock.append(colon); }
          const button = this.button('', 'time-part', event => this.openMenu('time', event.currentTarget, key, part));
          const number = document.createElement('span'), unit = document.createElement('small'); number.textContent = current.split(':')[part]; unit.textContent = part ? '分' : '时'; button.append(number, unit);
          button.setAttribute('aria-label', label + (part ? '分钟' : '小时')); button.setAttribute('aria-haspopup', 'dialog'); button.setAttribute('aria-expanded', 'false'); button.dataset.clock = key + '-' + part; button.disabled = !this[key]; clock.append(button);
        }
        wrap.append(title, date, clock); endpoints.append(wrap);
      }
      this.validate();
    }
  }
  customElements.define('moect-date-range', DateRange);
})();
