# Northwend runbook

What to do when something has to be done to the running app: deploy, undo,
restore, rotate keys, switch things off, close down, or answer a breach. Each
section is meant to be followed by someone who has never seen the code, with
the owner's logins to GitHub, the host, Neon, Anthropic, Resend and Finnhub.

PLAN 1b.1 (audit G6 and 1.10e). This page never holds a secret value. Where a
value goes, it says where, never what.

Contents:
- [Where things live](#where-things-live)
- [Deploy](#deploy)
- [Roll back](#roll-back)
- [Restore the database](#restore-the-database)
- [Rotate a key](#rotate-a-key)
- [Sign everyone out](#sign-everyone-out)
- [Turn off AI or email in an emergency](#turn-off-ai-or-email-in-an-emergency)
- [Turn a feature or gate on or off](#turn-a-feature-or-gate-on-or-off)
- [Shut down cleanly](#shut-down-cleanly)
- [After a breach](#after-a-breach)
- [Move to Render](#move-to-render)
- [Uptime check](#uptime-check)
- [Owner prerequisites](#owner-prerequisites)
- [Before turning on a gate](#before-turning-on-a-gate)
- [Monthly budget](#monthly-budget)

---

## Where things live

| What | Where |
|---|---|
| The code | GitHub. Two branches matter: `staging` and `main`. |
| The live app, today | Streamlit Community Cloud, an app that follows `main`. |
| The staging app | Streamlit Community Cloud, an app that follows `staging`. Its banner says "Staging copy". It has its own Neon database. |
| The live app, after step 4 | Render (`render.yaml`), at app.northwend.app, deploying `main`, behind Cloudflare's proxy (`docs/CLOUDFLARE.md`). The move: [Move to Render](#move-to-render). |
| Database roles | One owner role for `northwend-migrate`, one for the app, one for the jobs, once `docs/DB_ROLES.md` is done. |
| The databases | Neon. One project or branch for live, one for staging. |
| Scheduled jobs | GitHub Actions, `.github/workflows/scheduled-sync.yml` (prices, history, the Monday email, walk reminders). |
| The app's settings | Streamlit: the app's menu > Settings > Secrets. Render: the service's Environment. |
| The jobs' settings | GitHub: the repo's Settings > Secrets and variables > Actions. |
| Every setting's name and meaning | `.env.example` in the repo. |
| What the copy is running | Admin > System: version (commit), database, email, keys set or not, gates and flags. |

Restarting the app:
- **Streamlit Community Cloud:** after saving Secrets the app picks them up
  within a minute or two. If it doesn't, open the app's menu and choose
  Reboot app.
- **Render:** saving the Environment starts a new deploy by itself. Watch the
  service's Events until it says live.
- **GitHub jobs:** nothing to restart. The next run uses the new secret. To
  run one now: Actions > Scheduled sync > Run workflow.

---

## Deploy

Every change goes to staging first. Live only ever gets what staging had.

1. On your computer: `git checkout staging && git pull`.
2. Commit the change and `git push origin staging`.
3. On GitHub, open Actions > Tests. Wait until both jobs (unit tests and
   Postgres tests) are green for that commit.
4. Open the staging app. It redeploys by itself after the push. Admin >
   System shows the new version. Sign in (the seed logins from
   `manage_users.py seed-staging` work well) and look at what changed.
5. When it looks right, release it: `git push origin staging:main`.
   - This is a fast-forward. `main` is protected: it only takes commits whose
     Tests check passed, and never a force push.
   - If GitHub refuses, Tests isn't green on that commit yet. Wait, or fix it
     on staging. Never force.
6. The live app redeploys by itself:
   - **Today (Streamlit Community Cloud):** it follows `main`. Check Admin >
     System on the live app for the new version.
   - **After step 4 (Render):** `autoDeploy` is on for `main`. Render
     installs `requirements.txt`, starts the app, and checks
     `/_stcore/health`. If the check fails, the old version keeps serving.
     Watch the service's Events and Logs until it says live.
7. Watch your email for an hour. A new error on the live copy emails
   `ALERT_EMAIL` (at most once an hour per kind).

Database changes: the app adds new tables and columns itself when it starts.
`northwend-migrate` runs the same thing on purpose. Once the database roles
are split (`docs/DB_ROLES.md`, with `NORTHWEND_SKIP_SCHEMA_SETUP=1`), the app
can't: when `SCHEMA_VERSION` in `portfolio.py` goes up, run
`northwend-migrate` as the owner role on each database before its release -
staging's before step 2, live's before step 5. See DB_ROLES.md, "Schema
changes from now on".

---

## Roll back

First ask: is the bad part behind a flag? If so, turning the flag off is
faster than any rollback ([see below](#turn-a-feature-or-gate-on-or-off)).

**The normal way: revert through staging.**
1. `git checkout staging && git pull`
2. `git revert --no-edit <bad commit>` (one revert per bad commit, newest
   first).
3. `git push origin staging`. Wait for Tests to go green. Check staging.
4. `git push origin staging:main`.

**Faster, while the revert goes through:**
- **Render:** the service > Events > pick the last good deploy > Rollback.
  The old version serves at once. `main` still has the bad commit, so do the
  revert above too. Render can turn auto-deploy off after a rollback: check
  the service's settings and turn it back on once `main` is fixed.
- **Streamlit Community Cloud:** there is no rollback button. Revert in git.

**The database is not rolled back.** Old code runs fine with the extra
tables and columns a newer version added. If data itself was damaged, see
the next section.

---

## Restore the database

Neon keeps the database's history for a set window and can make a branch as
it was at any moment inside it. The window is set by the Neon plan: about 6
hours today (what the disclosures say), 7 days once decision D6 is done.
Start quickly.

1. **Write down the time** (UTC) just before the problem started.
2. **Stop the damage.** If a job is writing bad data: GitHub Actions >
   Scheduled sync > the "..." menu > Disable workflow. If the app is, turn
   the feature off by flag, or reboot the app after a revert.
3. **Make a branch from that time.** Neon console > the live project >
   Branches > Create branch. Parent: the live branch. Choose the past point
   in time and enter the time from step 1. Name it `restore-YYYY-MM-DD`.
4. **Get its connection string.** Connect (or Connection details) > choose
   the new branch > pooled connection. Copy it. Don't paste it anywhere but
   the places below.
5. **Count rows** on both the new branch and the live one, and compare. From
   the repo on your computer (it needs only `requirements.txt` installed):

   ```
   python scripts/restore_check.py --db "<new branch's string>" --against "<live string>"
   ```

   It lists every table in `schema_pg.sql` with both counts and the
   difference, and says if a table is missing from either. It only reads:
   the session is read-only, it never sets the schema up, and it never
   prints the connection strings. Counts only - nobody reads anyone's
   holdings to check a restore. (No Python to hand? In Neon's SQL Editor on
   each branch, `SELECT COUNT(*) FROM users;` and the same for `snapshots`,
   `positions`, `plans`, `advisor_notes`.)
6. **Swap.** Put the new branch's connection string in every place the old
   one was: `PORTFOLIO_DB` in the live app's settings (Streamlit Secrets, or
   Render's Environment), and the `DATABASE_URL` GitHub secret. Restart the
   app. Check Admin > System and sign in.
7. **Make it the main branch.** In Neon, set the restored branch as the
   default branch, so the plan's history keeps covering it. Re-enable the
   workflow if you disabled it.
8. **Delete the old branch** once you're sure (a day at most). A leftover
   branch keeps data people deleted, and the disclosures promise it goes.

Anything written between the problem and the swap (new sign-ups, imports)
is on the old branch only. Tell the people affected, plainly.

Never copy live data into staging, or onto your own computer.

**Quarterly restore drill** (D6; first one at step 4). Don't swap anything.

- [ ] Make a branch of the live project from one hour ago (steps 3 and 4).
- [ ] Count rows on both (step 5):
      `python scripts/restore_check.py --db "<drill branch>" --against "<live>"`.
      No table missing; the differences are only the last hour's (a few
      sign-ins, prices, sessions).
- [ ] Minutes from start to counts: ____
- [ ] Delete the drill branch. Nothing points at it.
- [ ] Add a line below.

| Date | Who | Minutes | Result |
|---|---|---|---|
| | | | |

---

## Rotate a key

The pattern is the same for every key: make the new one, put it in every
place the old one lives, restart, check it works, then revoke the old one.
Staging has keys of its own: rotate those separately.

| Key | Made at | Lives in | Then |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic console > API keys, in the right workspace (production, or staging's own) | App settings (live and staging each their own). Render's Environment after step 4. Not in GitHub. | Restart the app. Ask Northwend one question in the app. Revoke the old key. |
| `RESEND_API_KEY` | resend.com > API Keys (sending access, the northwend.app domain) | App settings, the `RESEND_API_KEY` GitHub secret, Render | Restart the app. Admin > System says email is sending. Ask for a password reset to your own address. Revoke the old key. |
| `FINNHUB_API_KEY` | finnhub.io > Dashboard | The `FINNHUB_API_KEY` GitHub secret, app settings, Render | Actions > Scheduled sync > Run workflow: the refresh job is green. A new Finnhub key may end the old one at once. |
| The Neon password (inside `PORTFOLIO_DB` and `DATABASE_URL`) | Neon console > the project > Roles > the app's role > Reset password | `PORTFOLIO_DB` in app settings, the `DATABASE_URL` GitHub secret, Render | The old password stops at once, so the app is down until the new string is in. Do it at a quiet hour, all places in one go. Restart the app. Run the workflow. |
| GitHub | - | Holds copies of the keys above, not keys of its own | If GitHub itself may be exposed: change the password, check two-factor is on, delete unused personal access tokens, review which apps have access (Streamlit, Render), then rotate every key above, since a changed workflow could have read any secret. |
| Paddle keys (step 6) | Paddle dashboard: the API key, and any notification secret | Render's Environment and the GitHub secret for the reconciliation job. Staging gets sandbox keys only. | Restart the app. Run the reconciliation job. A test will fail on a live billing key in the repo (coming in this step, PLAN 1b.4). |

`ALERT_EMAIL`, `APP_URL`, `NORTHWEND_ADMINS`, `NORTHWEND_GATES` and
`NORTHWEND_FLAGS` aren't secrets, but they live in the same places.

---

## Sign everyone out

Use it when sessions may be stolen, after a breach, or after a change to how
sign-in works.

- **The command (coming in this step, PLAN 1b.2):**
  `python manage_users.py --db "<live connection string>" sign-out-all`.
  Every open tab and every "stay signed in" device has to sign in again.
- **Until that lands:** in the live database run
  `DELETE FROM login_sessions;` (this ends every "stay signed in" device),
  then reboot the app (this drops the tabs that are open). Both steps are
  needed.
- **One account only:** `manage_users.py passwd <login>` (a new password
  signs out their open tabs too), or `manage_users.py reset-two-step <login>`
  (signs them out everywhere).

People just see the sign-in page. Nothing is lost.

---

## Turn off AI or email in an emergency

**AI** (a cost spike, a bad answer pattern, a provider problem):
1. Fastest: in the Anthropic console, disable the app's key. Every AI
   feature then fails calmly at once, with no restart.
2. Then, in the app's settings, `NORTHWEND_AI_CEILING_USD = "0"` and
   restart. Every AI feature shows the calm "resting" line, and everything
   else works. (Or remove `ANTHROPIC_API_KEY`: the features say they aren't
   available.)
3. Screenshot reading only: take `screenshot_ai` out of `NORTHWEND_FLAGS`.
4. To turn it back on: re-enable the key, put the ceiling back, restart.

**Email** (a mistake in an email, sending to the wrong people):
1. In the app's settings, `MAIL_DRY_RUN = "1"` and restart. The app logs
   emails instead of sending them. Confirm and reset emails stop too, so
   answer support@ by hand meanwhile.
2. The jobs don't read `MAIL_DRY_RUN`. To stop their email: delete the
   `RESEND_API_KEY` GitHub secret (the Monday email and walk reminders then
   skip; job-failure alerts stop too), or disable the Scheduled sync
   workflow (this also stops price updates).
3. Everything at once, everywhere: revoke the key in Resend.
4. To turn it back on, undo the same steps and restart.

---

## Turn a feature or gate on or off

Two settings, both off unless set (`flags.py`):
- `NORTHWEND_FLAGS`: the features turned on, for example `"walk,screenshot_ai"`.
  The names are in `flags.FEATURES`.
- `NORTHWEND_GATES`: the legal gates turned on, for example `"L0"`. Only L0,
  L1, L2 and L3 exist. There is no L4 and never will be.

Where: the app's settings (live and staging each their own), Render's
Environment after step 4, and the `NORTHWEND_FLAGS` GitHub secret (the walk
reminders job reads it). Restart the app, then check Admin > System, which
lists every gate and flag and any name it doesn't know.

Staging turns everything on. Live turns on only what the owner approved.

**The rule: never turn on a gate without its checklist** in
[Before turning on a gate](#before-turning-on-a-gate) ticked, and the
attorney's sign-off dated in [Owner prerequisites](#owner-prerequisites).
Turning a gate off is always allowed. `docs/LEGAL_GATES.md` says what people
see with each gate off. For example, with L0 off, Create account asks for an
invite code.

Today the live copy has L0 on, to keep sign-up open as it was (an owner
decision at step 1a.9). The L0 checklist is still owed before the beta opens
wider.

---

## Shut down cleanly

1. **Pick the date.** Give at least the notice the Terms promise (the draft
   leaves the number of days to the owner and the lawyer).
2. **Tell people.** Advisors first, so they can export their records and
   tell their clients. Then everyone with a confirmed email (no figures in
   it, like every Northwend email). Put the same note on northwend.app
   (`website/`, then `python website/build.py`) and on the About page
   (`disclosures.py`). The app has no bulk-email tool yet; send it from
   Resend.
3. **Open the export window.** Account > Export everything works for
   everyone until the last day. Advisors also have the client record export.
   To save money meanwhile: `NORTHWEND_AI_CEILING_USD = "0"`, and take L0
   out of `NORTHWEND_GATES` so no one new signs up.
4. **Stop the jobs.** Disable the Scheduled sync workflow.
5. **Close the app.** There is no "closed" page yet. `MOVED_TO` is the wrong
   tool here: it says the account came along to a new address. Stop the app
   instead (delete the Streamlit app, or suspend the Render service) and
   point app.northwend.app at a page on the website that says Northwend has
   closed.
6. **Delete.** First keep only what the attorney says must be kept (consent
   records and access logs under B6, billing records for tax), exported and
   stored offline and encrypted. Then delete the Neon project (all branches),
   the Streamlit apps or Render service, the GitHub secrets, and the keys at
   Anthropic, Resend and Finnhub. Neon's history goes when its window
   passes.
7. **Keep the domain** for at least a year, so nobody else can catch old
   links and emails.

---

## After a breach

Stay calm and keep to what's true. Say only what you know.

1. **Contain.** Rotate the keys involved (all of them if unsure). Sign
   everyone out. Turn off whatever is leaking (a flag, AI, email). Disable
   the jobs if they're involved.
2. **Keep the evidence.** Write down times as you go. Don't clear error
   records or logs. If useful, make a Neon branch at the current time; it
   holds personal data, so delete it once it's no longer needed.
3. **Work out the facts.** Which accounts, and how many. Which kinds of data.
   Counts and kinds, not anyone's figures. What Northwend holds: logins and
   emails, holdings (symbols, shares, cost, value, cash), plans, profile
   answers, advisor notes. What it never holds: brokerage logins, full
   account numbers (only the last 3 digits), uploaded files. Passwords are
   stored only as hashes.
4. **Tell, in this order:**
   1. The attorney, the same day.
   2. The cyber insurer. Policies usually need prompt notice.
   3. Affected advisors, within the time the advisor security page promises
      (still a draft: the lawyer sets the number), so they can meet their own
      duties to their clients.
   4. Affected people and any regulators, as the law requires. The attorney
      says which laws and which states. The Privacy Policy draft promises
      only "we will tell you as the law requires": promise nothing beyond it.
5. **What to say.** Short and plain:
   - what happened, and when;
   - what data was involved, for how many accounts, and what wasn't;
   - what Northwend has done about it;
   - what they can do: change their password, turn on two-step sign-in, and
     ignore any email asking for a password or brokerage login (Northwend
     never asks);
   - who to contact: support@northwend.app.
   Send an update when more is known. Never guess.
6. **Afterwards.** Write down what happened, how it was found, what fixed it
   and the test that now guards it. Update this runbook.

---

## The AI eval

Ask Northwend's eval set (`evals/`, docs/AI_PLAN.md section 8): 64 cases in
groups A-J. Its checker runs free in Tests on canned answers
(`tests/test_evals.py`). Asking the real model is by hand only - never in
CI, which has no key - and costs about $2 a pass on the chat model.

1. In the Anthropic console, use the separate eval workspace with its own
   spend limit (about $50 a month). Never the production key.
2. In the shell for this run only (not `.env`, not any app's secrets):
   `ANTHROPIC_API_KEY_EVAL=` its key (PowerShell: `$env:ANTHROPIC_API_KEY_EVAL = "..."`).
3. From the repo root, the baseline on today's prompt and the stricter
   policy, three samples each:
   `python -m evals.run --samples 3 --rules current --out ../eval-current.json`
   `python -m evals.run --samples 3 --rules policy --out ../eval-policy.json`
   `--group A` or `--case A1,A6` narrows it, `--judge` adds a second opinion
   from the cheap model, `--dry-run` builds the prompts and sends nothing.
4. Any failed case fails the run. Triage each one, never re-run until
   green: fix the prompt or the rules, or - if the checker was wrong - fix
   `evals/checker.py`/`ai_policy.py` and add the answer to
   `evals/canned.py` so Tests holds the fix. Keep the `--out` files outside
   the repo: they hold the answers (made-up data only).

## Move to Render

PLAN step 4 (audit 1.8b, 1.8c, 1.10a): the live app moves from Streamlit
Community Cloud to Render, at app.northwend.app, behind Cloudflare. The code
is ready (`render.yaml`, `hosting.py`, `docs/CLOUDFLARE.md`). Staging stays
on Community Cloud. Do the steps in order; each says when it's done. About
two hours, plus a month before the last step. Nobody is signed out and no
data moves: both copies use the same Neon database.

Before you start:
- [ ] A Render account, with access to the GitHub repo (Render asks when you
      connect it).
- [ ] The live app's Streamlit Secrets open in another tab (its menu >
      Settings > Secrets): Render needs the same values.
- [ ] Production keys only for production (1.5c): the Anthropic key from the
      production workspace, the live Resend key, the live Neon string.
      Staging keeps its own (its own Anthropic workspace, `MAIL_DRY_RUN=1` or
      a test-only Resend key). Never paste a staging key into Render.

### 1. Create the Blueprint
- [ ] Render dashboard > **New** > **Blueprint** > pick the repo. Render
      reads `render.yaml` and shows one web service, `northwend`, Starter
      plan, branch `main`.
- [ ] Render asks for each `sync: false` setting. Copy each from the live
      app's Secrets: `PORTFOLIO_DB`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`,
      `FINNHUB_API_KEY`, `NORTHWEND_ADMINS`, `ALERT_EMAIL`,
      `NORTHWEND_GATES` (today `L0`), `NORTHWEND_FLAGS`,
      `NORTHWEND_AI_CEILING_USD`. `AI_ZDR`: `0` until Anthropic has confirmed
      zero data retention in writing. The rest (`NORTHWEND_ENV=production`,
      `CLIENT_IP_HEADER`, `APP_URL`, the Streamlit settings) come from the
      file - don't add them by hand.
- [ ] **Apply**. Watch the service's Events until the deploy is **live**.

Done when: the deploy is live and its health check passed.

### 2. Check it on onrender.com
The service's page shows its address, like `https://northwend.onrender.com`.
Don't share it.
- [ ] `https://<service>.onrender.com/_stcore/health` answers `ok`.
- [ ] Sign in with your admin login (two-step code too). Home, Plan and
      Account look as on the live app.
- [ ] Admin > System: runs on Render, the version is `main`'s latest commit,
      the database is Postgres, email is sending, every key is set, the
      gates and flags match the live app's.
- [ ] Render > Logs: no errors.

Emails sent from this copy already link to app.northwend.app (`APP_URL`),
which doesn't work yet; avoid sending any during the check.

Done when: all four are ticked.

### 3. Add the domain in Render
- [ ] The service > **Settings** > **Custom Domains** > **Add**:
      `app.northwend.app`. Render shows the `CNAME` target to use (the
      service's onrender.com name).

### 4. Cloudflare in front
- [ ] Follow `docs/CLOUDFLARE.md` sections 1 to 7, in order: the `app`
      record (DNS only until Render verifies, then Proxied), Full (strict),
      WebSockets, the "never cache" rule, the six security headers,
      Email Address Obfuscation and the other script features off, and the
      Render address turned off if offered.

Done when: Render shows `app.northwend.app` Verified with its certificate,
and the record in Cloudflare is Proxied.

### 5. Check app.northwend.app
- [ ] `docs/CLOUDFLARE.md` section 8: the pages work, the six headers are
      there, nothing is cached, health says `ok`.
- [ ] securityheaders.com grade: ____ (aim: A). Date: ____
- [ ] Sign up a test account with an address you own, confirm it, delete it
      (Account > Delete my account): sign-up, email links and the
      per-address limits work through the proxy.

Done when: all three are ticked.

### 6. Point everything at the new address
- [ ] The website's buttons: `APP_URL` in `website/build.py` to
      `https://app.northwend.app/`, `python website/build.py`, commit
      through staging and release (Cloudflare Pages redeploys the site).
- [ ] GitHub > Settings > Secrets and variables > Actions: the `APP_URL`
      secret to `https://app.northwend.app/` (links in the Monday email and
      the walk reminders).
- [ ] The uptime monitors ([Uptime check](#uptime-check)).

### 7. Turn the old app into a signpost
- [ ] Community Cloud > the live app > Settings > **Secrets**: delete
      everything, and add only `MOVED_TO = "https://app.northwend.app"`.
      Save. The old app needs no database or key for its "has moved" page,
      so none stays on Community Cloud.
- [ ] Open the old address with `?page=plan` on the end: it says Northwend
      has moved, and its button goes to `https://app.northwend.app/?page=plan`
      (old confirm and reset links in inboxes keep working that way).
- [ ] Recommended, since Community Cloud held them: rotate each key that
      lived there ([Rotate a key](#rotate-a-key)) at a quiet hour - the new
      ones go only to Render and GitHub. The Neon password goes with the
      database roles (`docs/DB_ROLES.md`, step 5).

### 8. Name the real hosts
Until now the About page on each copy named its own host by itself, and the
website named both ("moving to Render"). Now that the move is done:
- [ ] In `disclosures.py`: `HOST_MOVED = True`, and `LAST_UPDATED` to
      today's date (who sees the app's traffic changed, so everyone is told
      at their next sign-in). The tests that pin the date say where to
      change them too.
- [ ] `docs/legal/`: remove the two "[OWNER: written for after the move ...]"
      notes.
- [ ] `python website/build.py`; commit through staging and release.

### 9. A month later: delete the old app
- [ ] Nobody has opened the old address for a while (its Community Cloud
      analytics, if shown), and the date is at least a month after step 7:
      ____
- [ ] Community Cloud > the old live app > **Delete**. Keep the staging app.
- [ ] Monthly budget: the Streamlit line ends, the Render line starts.

**Done when** (PLAN step 4):
- [ ] The app is served at app.northwend.app from Render behind Cloudflare,
      with the six headers (step 5).
- [ ] A restore drill has passed ([the drill](#restore-the-database), with
      `scripts/restore_check.py`), and its line is in the table there.
- [ ] The uptime check is live ([Uptime check](#uptime-check)).
- [ ] Community Cloud shows "has moved" (step 7).
- [ ] The disclosures name the real hosts (step 8).
- [ ] Then, not blocking the rest: the database roles are split
      (`docs/DB_ROLES.md`).

---

## Uptime check

PLAN step 4.4 (G4). A free outside service checks the app and the website
every few minutes and emails you when one stops answering. Nothing is added
to any page: no badge, no script, no status-page widget.

Any free monitor works (for example UptimeRobot's or Better Stack's free
plan). With UptimeRobot:

1. Sign up with the address that should get alerts (the same as
   `ALERT_EMAIL` is a good choice). Turn on two-step sign-in for it.
2. **New monitor** > type **Keyword**, URL
   `https://app.northwend.app/_stcore/health`, keyword `ok` (alert when it's
   missing), every 5 minutes. Name: `Northwend app`.
   `/_stcore/health` is Streamlit's own check - the one Render uses before it
   switches to a new deploy (`render.yaml`). It says the server is up; the
   database and the jobs have their own alerts (error emails, "Tell the
   admin it failed").
3. **New monitor** > type **HTTP(s)**, URL `https://northwend.app/`, every
   5 minutes. Name: `Northwend website`.
4. Alert contacts: your email, on both. Leave any public status page off.
5. Test it once: pause the Render service (Settings > Suspend) at a quiet
   hour, wait for the email, resume it.

Cloudflare's Bot Fight Mode stays off (`docs/CLOUDFLARE.md`), so the
monitor's requests aren't challenged.

| Monitor | Set up on | Alerts go to |
|---|---|---|
| App (`/_stcore/health`) | ____ | ____ |
| Website | ____ | ____ |

---

## Owner prerequisites

Not code, but required before some gates (decision B8; not legal advice).
Fill in the blanks as each is done.

| Item | Needed by | Done on | Details |
|---|---|---|---|
| Business entity (single-member LLC or local equivalent; ask the attorney and an accountant which form) | Before the first paid seat (L1). Ideally before open sign-up (L0). | ____ | Name: ____ |
| Technology errors-and-omissions insurance | Before L1 | ____ | Insurer, policy, renews: ____ |
| Cyber insurance | Before L1 | ____ | Insurer, policy, renews: ____ |
| Accountant consulted (entity, sales tax, how long to keep billing records) | Before L1 | ____ | ____ |
| Billing provider approval (Paddle, B2) | Before L1 | ____ | ____ |
| Securities attorney engaged | Before any gate | ____ | Name: ____ |

**The attorney's sign-off, per gate.** One line each, dated. A gate is never
turned on before its line is filled in.

| Gate | What they sign off | Signed by | Date | Notes |
|---|---|---|---|---|
| L0 Beta baseline | Terms, Privacy Policy, "educational, not advice", 18+ and US residency, deletion and export | ____ | ____ | ____ |
| L1 Advisor seats and billing | Advisor agreement, billing copy, flat fee only, seat lapse | ____ | ____ | ____ |
| L2 Directory and intros | Directory copy, filters, ordering, two-step consent text, the "advice is the advisor's" line, state coverage | ____ | ____ | ____ |
| L3 Conclusion policy | The example-mix rewrite and Ask Northwend's conclusion policy, with the eval set | ____ | ____ | ____ |
| L4 In-house advice | Never in scope. No setting exists. | - | - | - |

---

## Before turning on a gate

From `docs/LEGAL_GATES.md`. Tick every box for a gate, in staging first,
before its name goes into the live `NORTHWEND_GATES`.

**For every gate:**
- [ ] The attorney's sign-off for this gate is dated above.
- [ ] The owner prerequisites this gate needs are done.
- [ ] Turned on in staging with seed data. Tests green. Every page it
      changes looked at.
- [ ] The copy this gate changes (LEGAL_GATES.md section 7) is updated.
      Disclosures are reworded, never removed.
- [ ] `disclosures.py` and `docs/legal/` agree. The website is rebuilt.
- [ ] After turning it on: Admin > System shows it. Date: ____

### L0 Beta baseline
- [ ] The Terms of Use and Privacy Policy are published, with no `[LAWYER]`
      or `[OWNER]` left in them.
- [ ] The "educational, not advice" disclosure is signed off.
- [ ] 18+ and US residency are asked and stored, each with its time (built
      in step 1a.9).
- [ ] Deleting an account and Export everything both work (try them on
      staging).
- [ ] The retention schedule (D5) is in the disclosures and the Privacy
      Policy, and the tidy job runs (`northwend-tidy`, coming in this step).
- [ ] The backup window the disclosures state matches the Neon plan (D6),
      and a restore drill has passed.
- [ ] The AI ceiling and the Anthropic console limit are set (B7: open
      sign-up only with the ceiling in place).
- [ ] The business entity is formed (strongly recommended).

### L1 Advisor seats and billing
- [ ] The advisor agreement text is final (no longer marked "beta").
- [ ] The billing copy is final: one flat price per seat, never per client.
      The test that billing never reads client or intro counts passes.
- [ ] Seat lapse works as decided (B5: 30 days of read and export).
- [ ] Step 4 is done: money never runs on Streamlit Community Cloud.
- [ ] The business entity is formed. E&O and cyber insurance are in place.
- [ ] The billing provider has approved the account. Staging has
      test-mode keys only; live keys are only in Render and GitHub.
- [ ] The separate billing feature flag is ready, off until this gate is on.
- [ ] Every "free / paid by no one" line in LEGAL_GATES.md section 7 is
      reworded.
- [ ] The reconciliation job has its own "Tell the admin it failed" step.

### L2 Directory and intro flow
- [ ] The directory copy and its filters are signed off (B4). It's
      alphabetical only, and a test checks there's no ranking.
- [ ] The two-step consent text is final and stored word for word with each
      consent.
- [ ] Consent records and advisor access logs are append-only and kept 7
      years (B6), and the Privacy Policy says so.
- [ ] The standing line "advice is the advisor's, not Northwend's", with
      name and firm, is on every advisor artefact.
- [ ] State coverage is handled as the attorney decided.
- [ ] The Terms no longer say Northwend "does not refer clients" (reworded
      by the attorney).
- [ ] Licence checks are stored, and the yearly re-check job runs (D15).
- [ ] Step 4 is done.

### L3 Conclusion policy
- [x] The example-mix rewrite ("common starting points", the same for
      everyone) is in place - it is what L3 off shows (step 2). Turning L3
      on brings back the tailored example mix: the attorney decides whether
      that, or a version of it, may show.
- [ ] Ask Northwend's conclusion policy (`ai_policy.rules()` and the output
      check `ai_policy.check()`) is wired into every AI call by the gateway,
      and the eval set (64 cases, `evals/`) passes 3 of 3 samples with
      `python -m evals.run --samples 3 --rules policy` (see "The AI eval").
      Keep the run's summary as the evidence for the attorney.
- [ ] The Monthly Walk verdict points in LEGAL_GATES.md section 4 are
      settled.
- [ ] The guardrail gaps in LEGAL_GATES.md section 5 are closed.

---

## Monthly budget

Decision D16. Until seats pay, every cost lands on the owner. Fill in the
amounts, and compare the total with seat revenue each month.

| Item | Plan | Per month | Notes |
|---|---|---|---|
| Streamlit Community Cloud | Free | $0 | Until step 4 |
| Render | Starter (always on) | $____ | From step 4 |
| Neon | Plan with a 7-day restore window (D6) | $____ | Live and staging |
| Cloudflare | Free | $0 | DNS, proxy, headers, the website (Pages) |
| Resend | ____ | $____ | Check the monthly email allowance |
| Anthropic | Production workspace | $____ | The console spend limit: $____ |
| Market data | Finnhub free today; maybe a paid end-of-day plan (D4) | $____ | |
| Domain (northwend.app) | Yearly, divided by 12 | $____ | |
| Attorney | Divided by 12 | $____ | |
| Insurance (E&O and cyber) | Yearly, divided by 12 | $____ | |
| Business entity fees | Yearly, divided by 12 | $____ | |
| Accountant | Divided by 12 | $____ | |
| Billing provider fees | Later (step 6), per seat | $____ | About 5% plus 50 cents a seat (B2) |
| GitHub (code and Actions) | Free | $0 | |
| **Total** | | **$____** | |

**The AI ceiling.** Set `NORTHWEND_AI_CEILING_USD` to about half of the
Anthropic line, so the alerts at 50% and 80% come well before the money runs
out. Set the console limit at about 1.5 times the ceiling (`docs/AI_COSTS.md`
section 7.2), and give staging its own workspace with a small limit.

| Setting | Value | Set on |
|---|---|---|
| `NORTHWEND_AI_CEILING_USD` (live) | $____ | ____ |
| Anthropic console limit, production | $____ | ____ |
| Anthropic console limit, staging | $____ | ____ |
