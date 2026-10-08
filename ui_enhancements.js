// Small touch/desktop conveniences dashboard.py injects once per page load
// (st.html with unsafe_allow_javascript, so this runs in the app's own page):
//   - the menu's and the phone tab bar's background follows the light /
//     dark theme
//   - the menu's two small menus (+ Add holdings, the name menu) close after
//     a choice, and the page showing is marked for screen readers
//     (aria-current="page" on its item; the menus are navigation landmarks)
//   - pull down from the top of the page on a touch screen to refresh prices
//     (it presses a button keyed "pt_refresh" when the page has one; prices
//     now update on their own, so the dashboard doesn't show one)
//   - the name menu's theme button (key "pt_theme") flips light/dark by
//     picking the other theme in Streamlit's own menu, so the choice is saved
//     the same way as picking it there, and the page doesn't reload
// Everything drives Streamlit's own buttons, so if a Streamlit update renames
// them this just stops doing anything; the app itself keeps working.
(() => {
  if (window.__ptUi) return;
  window.__ptUi = true;

  const q = (sel) => document.querySelector(sel);

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

  // ---- the bars' background ----------------------------------------------
  // The menu and the phone tab bar (dashboard.py, keys "pt_menu" and
  // "pt_tabbar") need a solid background that follows light/dark; the theme
  // can change without the page rerunning, so keep --pt-bg equal to the
  // page's own background.
  // The same check marks the theme on the page root (data-pt-theme), which picks the
  // up / down / warning colors in dashboard.py's styles.
  const syncBg = () => {
    const bg = getComputedStyle(q(".stApp") || document.body).backgroundColor;
    if (!bg) return;
    const root = document.documentElement;
    root.style.setProperty("--pt-bg", bg);
    const [r, g, b] = (bg.match(/\d+/g) || [255, 255, 255]).map(Number);
    const theme = 0.299 * r + 0.587 * g + 0.114 * b < 128 ? "dark" : "light";
    if (root.dataset.ptTheme !== theme) root.dataset.ptTheme = theme;
  };
  syncBg();
  setInterval(syncBg, 250);   // a theme picked in Streamlit's own menu, too

  // ---- the page band -----------------------------------------------------
  // dashboard.py draws the deep blue band (_band_css) on the main area only
  // while it carries data-pt-band, set here when a band container is on the
  // page - Home's tall one (key "pt_home_band": data-pt-band="home") or the
  // slimmer one of the pages that opt in (key "pt_page_band": Plan, Money,
  // Learn, Life and Ask Northwend, "slim") - never on sign-in or any other
  // page - with where that container starts and ends, so whatever sits above
  // it (the staging note, a one-time agree box) stays off the navy.
  const syncBand = () => {
    const box = q('[data-testid="stMainBlockContainer"]');
    if (!box) return;
    const band = q('[data-testid="stMainBlockContainer"] .st-key-pt_home_band')
      || q('[data-testid="stMainBlockContainer"] .st-key-pt_page_band');
    if (!band) {
      if (box.hasAttribute("data-pt-band")) box.removeAttribute("data-pt-band");
      return;
    }
    const kind = band.classList.contains("st-key-pt_home_band") ? "home" : "slim";
    const boxTop = box.getBoundingClientRect().top;
    const r = band.getBoundingClientRect();
    const pad = parseFloat(getComputedStyle(box).paddingTop) || 0;
    // the band reaches the top of the page unless something is shown above it
    const top = r.top - boxTop <= pad + 24 ? 0 : Math.round(r.top - boxTop - 8);
    // the first thing after it overlaps the band's foot only when it's a card
    // (white, dark words); anything else starts below the hills
    let next = band.parentElement && band.parentElement.nextElementSibling;
    while (next && next.getBoundingClientRect().height === 0) next = next.nextElementSibling;
    const card = next && (next.querySelector(':scope > [data-testid="stVerticalBlock"]')
      || next.querySelector('[data-testid="stExpander"]'));
    // (Home in three parts, and the slim band pages' two: their parts are
    // cards, so it overlaps)
    const parts = next && next.querySelector(":scope > .st-key-pt_home_layout, :scope > .st-key-pt_page_layout");
    const overlaps = Boolean(parts) || (card && getComputedStyle(card.matches('[data-testid="stExpander"]')
      ? card.querySelector("details") || card : card).borderTopStyle !== "none");
    const set = (k, v) => { if (box.style.getPropertyValue(k) !== v) box.style.setProperty(k, v); };
    // no card: the band's own foot holds the hills (room below the words);
    // the slim band's hills are lower, so its cards overlap less
    set("--pt-band-pad", kind === "home" ? (overlaps ? "0px" : "3rem") : (overlaps ? "1.5rem" : "3rem"));
    const end = Math.round(band.getBoundingClientRect().bottom - boxTop)
      + (overlaps ? (kind === "home" ? 80 : 48) : 0);
    set("--pt-band-top", top + "px");
    set("--pt-band-start", Math.round(r.top - boxTop) + "px");   // its words' top
    set("--pt-band-end", end + "px");
    if (box.getAttribute("data-pt-band") !== kind) box.setAttribute("data-pt-band", kind);
  };
  syncBand();
  setInterval(syncBand, 250);

  // ---- names for icon-only buttons ---------------------------------------
  // A button showing only an icon would be read out as the icon's name
  // ("close"); give screen readers what it does. Keyed by the widget key.
  const ICON_LABELS = [
    [/^st-key-wl_(?:w_)?del_(.+)$/, (m) => `Remove ${m[1]} from your watchlist`],
    [/^st-key-model_del_/, () => "Delete this model portfolio"],
    [/^st-key-me_del_/, () => "Remove this holding"],
    [/^st-key-me_cdel_/, () => "Remove this cash line"],
    [/^st-key-pt_hide$/, (m, btn) =>
      btn.textContent.includes("visibility_off") ? "Show amounts" : "Hide amounts"],
    // the name at the foot of the menu (on a phone just its icon) opens a menu
    [/^st-key-pt_me$/, (m, btn) => `Menu for ${wordsOf(btn)}`],
    // "Your investing profile (2/5)": the count said in words
    [/^st-key-assist_profile_open$/, (m, btn) =>
      wordsOf(btn).replace(/\s*\((\d+)\/(\d+)\)/, ", $1 of $2 questions answered")],
  ];
  // A Material icon beside words is decoration, but Streamlit has it read out
  // by name ("open_in_new See the months", "forum icon Ask Northwend"). A
  // button with words is named by its words alone, and an icon in a line of
  // text is hidden from screen readers. Icon-only buttons keep the names above.
  const ICONS = '[data-testid="stIconMaterial"], span[role="img"][translate="no"]';
  const wordsOf = (el) => {
    const copy = el.cloneNode(true);
    copy.querySelectorAll(ICONS).forEach((i) => i.remove());
    return copy.textContent.replace(/\s+/g, " ").trim();
  };
  const labelIconButtons = () => {
    const named = new Set();
    document.querySelectorAll('[class*="st-key-"] button').forEach((btn) => {
      const holder = btn.closest('[class*="st-key-"]');
      const cls = [...holder.classList].find((c) => c.startsWith("st-key-"));
      for (const [re, label] of ICON_LABELS) {
        const m = cls && cls.match(re);
        if (m) {
          const text = label(m, btn);
          if (btn.getAttribute("aria-label") !== text) btn.setAttribute("aria-label", text);
          named.add(btn);
          break;
        }
      }
    });
    document.querySelectorAll("button").forEach((btn) => {
      if (named.has(btn) || !btn.querySelector(ICONS)) return;
      // only a label Streamlit left empty, or one set here before
      if (btn.getAttribute("aria-label") && !btn.dataset.ptWords) return;
      const words = wordsOf(btn);
      if (!words) return;   // icon only: not ours to name
      if (btn.getAttribute("aria-label") !== words) btn.setAttribute("aria-label", words);
      btn.dataset.ptWords = "1";
    });
    document.querySelectorAll('[data-testid="stMarkdownContainer"] span[role="img"][translate="no"], '
                              + '[data-testid="stCaptionContainer"] span[role="img"][translate="no"]')
      .forEach((ic) => {
        if (ic.closest("button") || ic.getAttribute("aria-hidden") === "true") return;
        const line = ic.closest("p, li, summary, h1, h2, h3, h4, h5, h6") || ic.parentElement;
        if (line && wordsOf(line)) ic.setAttribute("aria-hidden", "true");
      });
    // the guide's avatar in the chat is a picture of a compass, not words
    document.querySelectorAll('[data-testid^="stChatMessageAvatar"]').forEach((av) => {
      if (av.getAttribute("aria-hidden") !== "true") av.setAttribute("aria-hidden", "true");
    });
    // a label with a link in it (the agree boxes: "...the [Terms of Use](https://...)")
    // reaches screen readers as Streamlit's raw text: read just the link's words
    document.querySelectorAll("[aria-label*=\"](\"]").forEach((el) => {
      const raw = el.getAttribute("aria-label");
      const words = raw.replace(MD_LINK, "$1");
      if (words !== raw) el.setAttribute("aria-label", words);
    });
  };
  const MD_LINK = /\[([^\]]+)\]\([^)]+\)/g;
  labelIconButtons();
  setInterval(labelIconButtons, 1000);

  // ---- the menu: where you are, and its two small menus ------------------
  // The items are Streamlit buttons; the one for the page showing is drawn as
  // "primary" (dashboard.py). Say so to screen readers too - aria-current -
  // and make each menu a navigation landmark.
  const CURRENT = ['.st-key-pt_menu [class*="st-key-nav"] button',
                   '.st-key-pt_tabbar button', '.st-key-pt_money_tabs button',
                   '[class*="st-key-menu_"] button', '.st-key-viewing_start button'].join(", ");
  const LANDMARKS = [[".st-key-pt_menu", "Main menu"], [".st-key-pt_tabbar", "Main menu"],
                     [".st-key-pt_money_tabs", "Money"]];
  const markCurrent = () => {
    for (const [sel, name] of LANDMARKS) {
      const bar = q(sel);
      if (bar && bar.getAttribute("role") !== "navigation") {
        bar.setAttribute("role", "navigation");
        bar.setAttribute("aria-label", name);
      }
    }
    document.querySelectorAll(CURRENT).forEach((btn) => {
      const on = btn.getAttribute("kind") === "primary";
      if (on && btn.getAttribute("aria-current") !== "page") btn.setAttribute("aria-current", "page");
      if (!on && btn.hasAttribute("aria-current")) btn.removeAttribute("aria-current");
    });
  };
  markCurrent();
  let marking = false;
  new MutationObserver(() => {
    if (marking) return;
    marking = true;
    requestAnimationFrame(() => { marking = false; markCurrent(); });
  }).observe(document.body, { subtree: true, childList: true, attributes: true,
                              attributeFilter: ["kind"] });

  // The menu's two small menus (+ Add holdings, key "pt_add", and the name menu,
  // "pt_me") are popovers, which stay open after a choice - close them, the
  // same way their own button would. (The theme button closes its menu
  // itself, below: Streamlit's own menu is opening just then.)
  const OPEN_MENUS = ['.st-key-pt_add', '.st-key-pt_me']
    .map((s) => s + ' [data-testid="stPopoverButton"][aria-expanded="true"]').join(", ");
  const closeMenus = () => document.querySelectorAll(OPEN_MENUS).forEach((m) => m.click());
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (!(t instanceof Element) || !t.closest('[data-testid="stPopoverBody"] button')) return;
    if (t.closest(".st-key-pt_theme")) return;
    setTimeout(closeMenus, 120);
  }, true);

  // the pull-to-refresh circle wears the page's own colors
  const paint = (el) => {
    const cs = getComputedStyle(q(".stApp") || document.body);
    el.style.background = cs.backgroundColor;
    el.style.color = cs.color;
  };

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

  // ---- movement between pages (ROADMAP T2) -------------------------------
  // A new page (the address's ?page= changes) fades in, and the route's
  // trail draws itself forward when its picture changes (a waypoint
  // reached). dashboard.py's styles do the moving (pt-page-enter,
  // pt-trail-advance); a device that asks for less motion gets none.
  const replay = (el, cls) => {
    if (!el) return;
    el.classList.remove(cls);
    void el.offsetWidth;  // restart the animation
    el.classList.add(cls);
  };
  const pageOf = () => new URLSearchParams(location.search).get("page") || "";
  let lastPage = pageOf();
  setInterval(() => {
    const p = pageOf();
    if (p !== lastPage) {
      lastPage = p;
      replay(q('[data-testid="stMainBlockContainer"]'), "pt-page-enter");
    }
  }, 120);
  // (each rerun builds the trail's images afresh, so remember the picture by
  // page and theme, not by element; a new element with the same picture
  // stays still)
  const trailSrc = new Map();
  setInterval(() => {
    for (const img of document.querySelectorAll("img.pt-trail")) {
      const key = pageOf() + "|" + img.className.replace(" pt-trail-advance", "");
      const was = trailSrc.get(key);
      if (was !== undefined && was !== img.src) replay(img, "pt-trail-advance");
      trailSrc.set(key, img.src);
    }
  }, 300);

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
        // picking a theme leaves the menu open; close it again, then the
        // name menu the switch was in, and repaint the bars straight away
        setTimeout(() => {
          if (q('[data-testid="stMainMenuList"]')) menu.click();
          setTimeout(() => { closeMenus(); syncBg(); }, 60);
        }, 50);
      };
      setTimeout(pick, 0);
    }, 60);
  }, true);
})();
