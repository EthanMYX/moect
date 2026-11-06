const MoectMedia = {
  mount(root) {
    const dialog = document.createElement("dialog");
    dialog.className = "moect-image-viewer";
    dialog.setAttribute("aria-label", "图片预览");
    const toolbar = document.createElement("div");
    toolbar.className = "moect-image-toolbar";
    const frame = document.createElement("div");
    frame.className = "moect-image-frame";
    const image = document.createElement("img");
    image.alt = "预览图片";
    image.draggable = false;
    const status = document.createElement("div");
    status.className = "moect-image-status";
    status.setAttribute("role", "status");
    frame.append(image, status);
    const counter = document.createElement("span");
    counter.setAttribute("aria-live", "polite");
    let sources = [],
      index = 0,
      scale = 1,
      fitScale = 1,
      offsetX = 0,
      offsetY = 0,
      drag = null,
      previousFocus;
    const button = (text, title, callback) => {
      const element = document.createElement("button");
      element.type = "button";
      element.textContent = text;
      element.title = title;
      element.setAttribute("aria-label", title);
      element.onclick = callback;
      toolbar.append(element);
      return element;
    };
    const draw = () => {
      image.style.transform = `translate(${offsetX}px,${offsetY}px) scale(${scale})`;
    };
    const fit = () => {
      if (!dialog.open || !image.naturalWidth || !image.naturalHeight) return;
      fitScale = Math.min(
        Math.max(1, frame.clientWidth - 32) / image.naturalWidth,
        Math.max(1, frame.clientHeight - 32) / image.naturalHeight,
        1,
      );
      scale = fitScale;
      offsetX = (frame.clientWidth - image.naturalWidth * scale) / 2;
      offsetY = (frame.clientHeight - image.naturalHeight * scale) / 2;
      draw();
    };
    const updateZoom = (value, x = frame.clientWidth / 2, y = frame.clientHeight / 2) => {
      if (image.hidden || !image.naturalWidth) return;
      const next = Math.max(fitScale / 4, Math.min(8, value));
      const ratio = next / scale;
      // Keep the same image pixel under the pointer as the scale changes.
      offsetX = x - (x - offsetX) * ratio;
      offsetY = y - (y - offsetY) * ratio;
      scale = next;
      draw();
    };
    const stopDragging = () => {
      if (drag && frame.hasPointerCapture(drag.id)) {
        frame.releasePointerCapture(drag.id);
      }
      drag = null;
      frame.classList.remove("is-dragging");
    };
    const show = (number) => {
      stopDragging();
      index = Math.max(0, Math.min(sources.length - 1, number));
      image.hidden = true;
      status.hidden = false;
      status.textContent = "正在载入图片…";
      image.src = sources[index];
      counter.textContent = index + 1 + " / " + sources.length;
      previous.disabled = index === 0;
      next.disabled = index + 1 >= sources.length;
    };
    const previous = button("‹", "上一张", () => show(index - 1));
    const next = button("›", "下一张", () => show(index + 1));
    button("−", "缩小图片", () => updateZoom(scale / 1.25));
    button("＋", "放大图片", () => updateZoom(scale * 1.25));
    button("适应窗口", "适应窗口", fit);
    button("原始比例", "原始比例", () => updateZoom(1));
    toolbar.append(counter);
    button("关闭", "关闭图片预览", () => dialog.close());
    dialog.append(toolbar, frame);
    document.body.append(dialog);
    const style = document.createElement("style");
    style.textContent = `
      html.moect-image-open{overflow:hidden}
      .moect-image-viewer{position:fixed;inset:0;width:min(1100px,96vw);height:92vh;max-width:96vw;max-height:94vh;padding:0;border:1px solid var(--border,#ddd);border-radius:16px;background:var(--card,#fff);color:var(--foreground,#222);overflow:hidden}
      .moect-image-viewer[open]{display:flex;flex-direction:column}
      .moect-image-viewer::backdrop{background:#000b}
      .moect-image-toolbar{display:flex;align-items:center;gap:8px;flex-wrap:wrap;flex-shrink:0;padding:12px;border-bottom:1px solid var(--border,#ddd)}
      .moect-image-toolbar button{white-space:nowrap}
      .moect-image-toolbar span{margin-left:auto;font-size:12px}
      .moect-image-frame{position:relative;flex:1 1 0;min-height:0;width:100%;overflow:hidden;background:#8881;touch-action:none;cursor:grab}
      .moect-image-frame.is-dragging{cursor:grabbing}
      .moect-image-frame img{position:absolute;top:0;left:0;display:block;width:auto;height:auto;max-width:none;max-height:none;transform-origin:0 0;pointer-events:none;user-select:none}
      .moect-image-status{position:absolute;inset:0;display:grid;place-items:center;padding:20px;font-size:13px;color:var(--muted-foreground,#777);pointer-events:none}
      .moect-image-frame [hidden]{display:none}
      @media(max-width:600px){.moect-image-toolbar{padding:8px;gap:5px}}
    `;
    document.head.append(style);
    image.addEventListener("load", () => {
      if (!dialog.open) return;
      image.style.width = image.naturalWidth + "px";
      image.style.height = image.naturalHeight + "px";
      fit();
      image.hidden = false;
      status.hidden = true;
    });
    image.addEventListener("error", () => {
      image.hidden = true;
      status.hidden = false;
      status.textContent = "图片无法载入，请确认归档资源完整。";
    });
    new ResizeObserver(fit).observe(frame);
    root.addEventListener("click", (event) => {
      const target = event.target.closest("img");
      if (!target || !target.closest("a") || !root.contains(target)) return;
      const images = [
        ...root.querySelectorAll(
          "a > img.attachment, a.photo-link > img, .sticker a > img",
        ),
      ];
      const selected = images.indexOf(target);
      if (selected < 0) return;
      event.preventDefault();
      sources = images.map((item) => item.closest("a").href);
      previousFocus = document.activeElement;
      dialog.showModal();
      document.documentElement.classList.add("moect-image-open");
      show(selected);
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", () => {
      stopDragging();
      image.removeAttribute("src");
      document.documentElement.classList.remove("moect-image-open");
      previousFocus?.focus({ preventScroll: true });
    });
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        if (index > 0) show(index - 1);
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        if (index + 1 < sources.length) show(index + 1);
      }
    });
    frame.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        const bounds = frame.getBoundingClientRect();
        const pixels = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? frame.clientHeight : 1);
        const factor = Math.exp(-Math.max(-400, Math.min(400, pixels)) * 0.002);
        updateZoom(scale * factor, event.clientX - bounds.left, event.clientY - bounds.top);
      },
      { passive: false },
    );
    frame.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || image.hidden) return;
      drag = {id:event.pointerId, x:event.clientX, y:event.clientY, offsetX, offsetY};
      frame.setPointerCapture(event.pointerId);
      frame.classList.add("is-dragging");
      event.preventDefault();
    });
    frame.addEventListener("pointermove", (event) => {
      if (!drag || drag.id !== event.pointerId) return;
      offsetX = drag.offsetX + event.clientX - drag.x;
      offsetY = drag.offsetY + event.clientY - drag.y;
      draw();
    });
    frame.addEventListener("pointerup", stopDragging);
    frame.addEventListener("pointercancel", stopDragging);
    frame.addEventListener("lostpointercapture", stopDragging);
  },
};
