// Small touch/desktop conveniences dashboard.py injects once per page load
// (st.html with unsafe_allow_javascript, so this runs in the app's own page):
//   - a sidebar handle at the middle of the sidebar's right edge, in place of
//     Streamlit's small top-corner arrows
//   - the sidebar closes when you click or tap outside it
//   - pull down from the top of the page on a touch screen to refresh prices
//     (it presses a button keyed "pt_refresh" when the page has one; prices
//     now update on their own, so the dashboard doesn't show one)
//   - the sidebar's theme button (key "pt_theme") flips light/dark by picking
//     the other theme in Streamlit's own menu, so the choice is saved the same
//     way as picking it there, and the page doesn't reload
// Everything drives Streamlit's own buttons, so if a Streamlit update renames
// them this just stops doing anything; the app itself keeps working.
(() => {
  if (window.__ptUi) return;
  window.__ptUi = true;

  const q = (sel) => document.querySelector(sel);
  const sidebar = () => q('section[data-testid="stSidebar"]');
  const isOpen = () => sidebar()?.getAttribute("aria-expanded") === "true";

  // Icons are built with DOM calls, not markup strings: Streamlit's sanitizer
  // drops a whole script whose text looks like it contains HTML tags.
  const icon = (paths) => {
    const ns = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(ns, "svg");
    const attrs = { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
                    "stroke-width": "2.5", "stroke-linecap": "round", "stroke-linejoin": "round" };
    for (const [k, v] of Object.entries(attrs)) svg.setAttribute(k, v);
    for (const d of paths) {
      const p = document.createElementNS(ns, "path");
      p.setAttribute("d", d);
      svg.appendChild(p);
    }
    return svg;
  };

  const style = document.createElement("style");
  style.textContent = `
    [data-testid="stSidebarCollapseButton"], [data-testid="stExpandSidebarButton"] {
      visibility: hidden !important;
    }
    #pt-sb-handle {
      position: fixed; top: 50%; left: 0; z-index: 1000200;
      width: 22px; height: 64px; margin-top: -32px; padding: 0;
      display: flex; align-items: center; justify-content: center;
      border: 1px solid rgba(128, 128, 128, 0.35); border-left: none;
      border-radius: 0 12px 12px 0; cursor: pointer;
      box-shadow: 2px 0 6px rgba(0, 0, 0, 0.15);
      -webkit-tap-highlight-color: transparent;
    }
    #pt-sb-handle svg { width: 16px; height: 16px; transition: transform 0.2s; }
    #pt-sb-handle.open svg { transform: rotate(180deg); }
    /* phones: slimmer, and see-through while closed so it doesn't cover content */
    @media (max-width: 640px) {
      #pt-sb-handle { width: 16px; height: 56px; margin-top: -28px; }
      #pt-sb-handle:not(.open) { opacity: 0.7; }
      #pt-sb-handle svg { width: 13px; height: 13px; }
    }
    #pt-ptr {
      position: fixed; top: 0; left: 50%; z-index: 1000300;
      width: 36px; height: 36px; margin-left: -18px; border-radius: 50%;
      display: flex; align-items: center; justify-content: center;
      box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25); opacity: 0; pointer-events: none;
    }
    #pt-ptr svg { width: 20px; height: 20px; }
    #pt-ptr.spin svg { animation: pt-spin 0.8s linear infinite; }
    @keyframes pt-spin { to { transform: rotate(360deg); } }
  `;
  document.head.appendChild(style);

  // ---- sidebar handle ----------------------------------------------------
  const handle = document.createElement("button");
  handle.id = "pt-sb-handle";
  handle.type = "button";
  handle.appendChild(icon(["M9 6l6 6-6 6"]));
  document.body.appendChild(handle);

  const paint = (el) => {
    const sb = sidebar();
    if (!sb) return;
    const cs = getComputedStyle(sb);
    el.style.background = cs.backgroundColor;
    el.style.color = cs.color;
  };

  const place = () => {
    const sb = sidebar();
    if (!sb) { handle.style.display = "none"; return; }
    handle.style.display = "flex";
    const open = isOpen();
    handle.classList.toggle("open", open);
    handle.setAttribute("aria-label", open ? "Close sidebar" : "Open sidebar");
    handle.title = open ? "Close sidebar" : "Open sidebar";
    // the sidebar slides off to the left when closed, so its right edge is
    // where the handle belongs either way
    handle.style.left = Math.max(0, sb.getBoundingClientRect().right) + "px";
    paint(handle);
  };

  // follow the sidebar while it slides
  const track = (ms = 600) => {
    const until = performance.now() + ms;
    const step = () => { place(); if (performance.now() < until) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  };

  const setOpen = (open) => {
    if (open === isOpen()) return;
    const btn = open ? q('[data-testid="stExpandSidebarButton"]')
                     : q('[data-testid="stSidebarCollapseButton"] button');
    btn?.click();
    track();
  };

  handle.addEventListener("click", (e) => { e.stopPropagation(); setOpen(!isOpen()); });

  // close on a click or tap outside the sidebar - but not on the floating
  // parts of the sidebar's own widgets (dropdown menus, tooltips, dialogs)
  document.addEventListener("pointerdown", (e) => {
    if (!isOpen()) return;
    const t = e.target;
    if (!(t instanceof Element)) return;
    if (sidebar()?.contains(t) || handle.contains(t)) return;
    if (t.closest('[data-baseweb="popover"], [data-baseweb="tooltip"], [role="listbox"], ' +
                  '[role="dialog"], [data-testid="stToast"]')) return;
    setOpen(false);
  }, true);

  // on a phone the open sidebar covers the page, so picking a page closes it
  document.addEventListener("click", (e) => {
    if (window.innerWidth < 768 && e.target instanceof Element &&
        e.target.closest('[class*="st-key-nav_"]')) setTimeout(() => setOpen(false), 150);
  }, true);

  window.addEventListener("resize", () => track(200));
  new MutationObserver(() => track(600)).observe(document.body, {
    subtree: true, attributes: true, attributeFilter: ["aria-expanded"],
  });
  place();
  setInterval(place, 1000);  // catches reruns that rebuild the sidebar

  // ---- pull to refresh (touch screens) ----------------------------------
  const ptr = document.createElement("div");
  ptr.id = "pt-ptr";
  ptr.appendChild(icon(["M21 12a9 9 0 1 1-2.64-6.36", "M21 3v6h-6"]));
  document.body.appendChild(ptr);

  const PULL = 80;  // px of pull that triggers a refresh
  const scroller = () => q('[data-testid="stAppScrollToBottomContainer"]') ||
                         q('[data-testid="stMain"]');
  const refreshBtn = () => q(".st-key-pt_refresh button");
  let startY = null, pulled = 0;

  const show = (dist, armed) => {
    ptr.style.transform = `translateY(${Math.min(dist, PULL * 1.5) - 40}px) ` +
                          `rotate(${dist * 3}deg)`;
    ptr.style.opacity = Math.min(1, dist / PULL);
    ptr.style.outline = armed ? "2px solid currentColor" : "none";
  };
  const hide = () => {
    ptr.style.transition = "transform 0.2s, opacity 0.2s";
    ptr.style.opacity = 0;
    ptr.style.transform = "translateY(-40px)";
    setTimeout(() => { ptr.style.transition = ""; }, 250);
  };

  document.addEventListener("touchstart", (e) => {
    const sc = scroller();
    startY = null;
    if (e.touches.length !== 1 || !sc || sc.scrollTop > 0 || !refreshBtn()) return;
    if (isOpen() && sidebar()?.contains(e.target)) return;
    startY = e.touches[0].clientY;
    pulled = 0;
    paint(ptr);
  }, { passive: true });

  document.addEventListener("touchmove", (e) => {
    if (startY === null) return;
    const sc = scroller();
    pulled = e.touches[0].clientY - startY;
    if (pulled <= 0 || (sc && sc.scrollTop > 0)) { startY = null; hide(); return; }
    show(pulled * 0.6, pulled * 0.6 >= PULL);
  }, { passive: true });

  document.addEventListener("touchend", () => {
    if (startY === null) return;
    startY = null;
    const btn = refreshBtn();
    if (pulled * 0.6 >= PULL && btn) {
      ptr.classList.add("spin");
      show(PULL, false);
      btn.click();
      // the rerun replaces the page content; stop spinning once it settles
      setTimeout(() => { ptr.classList.remove("spin"); hide(); }, 2500);
    } else {
      hide();
    }
  }, { passive: true });

  // ---- theme switch -----------------------------------------------------
  const isDark = () => {
    const rgb = getComputedStyle(q(".stApp") || document.body).backgroundColor.match(/\d+/g);
    if (!rgb) return false;
    const [r, g, b] = rgb.map(Number);
    return (r * 299 + g * 587 + b * 114) / 1000 < 128;
  };
  document.addEventListener("click", (e) => {
    if (!(e.target instanceof Element) || !e.target.closest(".st-key-pt_theme button")) return;
    const want = `[data-testid="stMainMenuItem-theme-${isDark() ? "Light" : "Dark"}"]`;
    // Wait for this click to finish first: the menu takes a click that's
    // still in flight as a click outside it, and closes straight away.
    setTimeout(() => {
      const menu = q('[data-testid="stMainMenu"] button');
      if (!menu) return;
      if (!q('[data-testid="stMainMenuList"]')) menu.click();
      let tries = 0;  // the menu renders a moment after it opens
      const pick = () => {
        const item = q(want);
        if (!item) {
          if (++tries < 20) setTimeout(pick, 25);
          return;
        }
        item.click();
        // picking a theme leaves the menu open; close it again
        setTimeout(() => { if (q('[data-testid="stMainMenuList"]')) menu.click(); }, 50);
      };
      setTimeout(pick, 0);
    }, 60);
  }, true);
})();
