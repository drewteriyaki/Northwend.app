# Cloudflare in front of the app (app.northwend.app)

PLAN step 4.2, audit 1.8b. Northwend's domain is already on Cloudflare: its
DNS, and the website (northwend.app, Cloudflare Pages, headers from
`website/assets/_headers`). This page puts Cloudflare's proxy in front of the
app on Render as well, so the app gets the security headers that Streamlit and
Render can't send themselves. Follow it once, in order, during the move
([RUNBOOK, Move to Render](RUNBOOK.md#move-to-render), step 4). About 30
minutes. Everything here is on Cloudflare's free plan.

Menu names are Cloudflare's as of October 2026. If one has moved, search the
dashboard for the setting's name.

Contents:
- [1. The DNS record, proxied](#1-the-dns-record-proxied)
- [2. Encryption mode: Full (strict)](#2-encryption-mode-full-strict)
- [3. WebSockets on](#3-websockets-on)
- [4. Never cache the app](#4-never-cache-the-app)
- [5. The security headers](#5-the-security-headers)
- [6. Features that stay off](#6-features-that-stay-off)
- [7. The visitor's address](#7-the-visitors-address)
- [8. Check it](#8-check-it)
- [Why "A" and not "A+"](#why-a-and-not-a)

---

## 1. The DNS record, proxied

Do this after Render has the custom domain (RUNBOOK, Move to Render, step 5).

1. Cloudflare dashboard > the `northwend.app` zone > **DNS** > **Records** >
   **Add record**.
2. Type `CNAME`, Name `app`, Target the service's Render address (for example
   `northwend.onrender.com` - Render shows it on the service's page).
3. **Proxy status: DNS only** (grey cloud) to start. Render checks the domain
   and issues its certificate; with the proxy on, that check can fail.
4. In Render (the service > **Settings** > **Custom Domains**), wait until
   `app.northwend.app` shows **Verified** and the certificate **Issued**.
5. Back in Cloudflare, edit the record: **Proxy status: Proxied** (orange
   cloud). Save.

If Render ever says the certificate can't renew, set the record to DNS only
for a few minutes, let Render verify again, then turn the proxy back on.

## 2. Encryption mode: Full (strict)

**SSL/TLS** > **Overview** > encryption mode **Full (strict)**. Cloudflare
then talks to Render over HTTPS and checks Render's certificate. "Flexible"
would send the app's traffic to Render unencrypted, and Render's redirect to
HTTPS makes it loop. The setting covers the whole zone; the website on Pages
works with Full (strict) too.

Also under **SSL/TLS** > **Edge Certificates**: **Always Use HTTPS** on,
**Minimum TLS Version** 1.2.

## 3. WebSockets on

**Network** > **WebSockets**: **On** (the default). Streamlit draws every page
over one websocket (`/_stcore/stream`); without it the app never loads.

## 4. Never cache the app

Streamlit serves downloads (the Export everything ZIP, the plan PDF, CSV
exports) and pictures from `/media/...` addresses with no caching
instructions. Cloudflare caches `.zip`, `.pdf`, `.csv` and `.png` by default,
so someone's export could stay on Cloudflare's servers after the app has
forgotten it. One rule stops that for the app (the website is not affected):

1. **Caching** > **Cache Rules** > **Create rule**.
2. Name: `App: never cache`.
3. **Custom filter expression**: Field `Hostname`, Operator `equals`, Value
   `app.northwend.app` (the expression reads `(http.host eq "app.northwend.app")`).
4. **Cache eligibility: Bypass cache**. Deploy.

Streamlit's own scripts then come from Render each time; it's a small app,
so nobody will notice.

## 5. The security headers

One response-header rule adds them to every page and file the app serves.

1. **Rules** > **Overview** > **Create rule** > **Response Header Transform
   Rule** (older menus: **Rules** > **Transform Rules** > **Modify Response
   Header** > **Create rule**).
2. Name: `App: security headers`.
3. **If incoming requests match**: **Custom filter expression**, Field
   `Hostname`, Operator `equals`, Value `app.northwend.app`.
4. **Then**: for each line below, **Set static**, the header name and the
   value exactly as written (without the backticks). Six in all.

| Header | Value | What it does |
|---|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` | Browsers only ever use HTTPS for the app, for a year. The website already sends the same. |
| `X-Content-Type-Options` | `nosniff` | Browsers take each file as the type the app says, never guessing a script out of a download. |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | A link out of the app tells the other site only `https://app.northwend.app`, never the page or its `?query`. |
| `Content-Security-Policy` | `frame-ancestors 'none'` | No other site can show the app inside a frame (clickjacking). Only this part of a CSP: see below. |
| `X-Frame-Options` | `DENY` | The same for older browsers. |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), interest-cohort=()` | No page of the app can ask for the camera, microphone or location. The website sends the same. |

5. Deploy.

Don't add `preload` to the HSTS value: it can't be undone quickly. The app
needs nothing the headers block: it has no custom components, and the
two-step QR code, charts and downloads are drawn in the page itself. Check
them anyway in step 8.

## 6. Features that stay off

Northwend runs no third-party script on any page, and the website's CSP
(`default-src 'none'`, no `script-src`) blocks any script Cloudflare would add.
Check each of these is off:

- **Email Address Obfuscation** (**Scrape Shield**): **Off** for the whole
  `northwend.app` zone. It swaps every email address for "[email protected]"
  plus a decoding script - the website's CSP blocks that script, so the
  address would never show. (The website's build also wraps each email link
  in `email_off` markers, as a second guard.)
- **Rocket Loader** (**Speed** > **Optimization**): Off. It rewrites scripts
  and breaks Streamlit.
- **Web Analytics** / **Real User Measurements**: Off, and no **Zaraz**. They
  add a script to every page, which the disclosures say Northwend doesn't do.
- **Bot Fight Mode** (**Security** > **Bots**): Off. Its challenges can stop
  the app's websocket and set cookies the disclosures don't mention.
- **Automatic Signed Exchanges**, **Mirage**, **Polish**: not needed; leave
  off.

## 7. The visitor's address

Behind the proxy, Render sees Cloudflare's address, not the visitor's.
Cloudflare puts the visitor's in the `CF-Connecting-IP` header, and
`render.yaml` already sets `CLIENT_IP_HEADER` to `cf-connecting-ip`
(`hosting.py`), so the sign-up and email limits count per real visitor.

One gap: the service's own `onrender.com` address still answers without
Cloudflare, and there anyone can write that header themselves to dodge the
per-address limits. Once `app.northwend.app` works, turn the Render address
off if Render offers it (the service > **Settings** > **Custom Domains** >
**Render Subdomain**: Disabled). If it doesn't, the limits per account and
app-wide still hold.

## 8. Check it

1. Open `https://app.northwend.app/` in a private window. Sign in with a
   test account, open Home, Plan (the charts), Account (Export everything
   downloads), and the two-step setup page (the QR code shows). The browser's
   developer console shows no "Refused to frame" or "Refused to load" errors
   from the app's own pages.
2. In a terminal:
   `curl -sI https://app.northwend.app/ | grep -iE "strict-transport|x-content-type|referrer-policy|content-security|x-frame|permissions-policy|cf-cache-status"`
   shows the six headers, and `cf-cache-status` is `DYNAMIC` or `BYPASS`
   (never `HIT`).
3. `curl -s https://app.northwend.app/_stcore/health` answers `ok`.
4. Go to <https://securityheaders.com>, enter `https://app.northwend.app/`,
   tick **Hide results** (so the scan isn't listed publicly), and scan. Aim
   for **A** with all six headers green. Note the date and grade in the
   RUNBOOK's move checklist.
5. Scan `https://northwend.app/` too: it should still show its own headers
   (Pages), and the About page's email address shows as an address, not
   "[email protected]".

## Why "A" and not "A+"

securityheaders.com gives A+ only for a full Content Security Policy - one
that says where scripts, styles and connections may come from - without
weak spots. Streamlit can't take one: its page is built by scripts and
styles written inline, it injects styles as it draws, and the app adds its
own small script (`ui_enhancements.js`). A full CSP for it would need
`'unsafe-inline'` (and probably `'unsafe-eval'` for the charts), which the
scanner marks down anyway and which would protect little. So the app's CSP
carries only `frame-ancestors 'none'` - the part that matters for a
logged-in finance app (no framing) - and the grade is A. If the scanner
shows A+, that's fine too; what matters is that all six headers are there.

The website, which runs no scripts at all, has the full CSP
(`website/assets/_headers`).
