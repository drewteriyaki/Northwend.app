# Northwend runbook

What to do when something has to be done to the running app: deploy, undo,
restore, rotate keys, switch things off, close down, or answer a breach. Each
section is meant to be followed by someone who has never seen the code, with
the owner's logins to GitHub, the host, Neon, Anthropic, Resend and Finnhub.

PLAN 1b.1 (audit G6 and 1.10e). This page never holds a secret value. Where a
value goes, it says where, never what.

Contents:
- [Where things live](#where-things-live)
- [Calendar](#calendar)
- [Deploy](#deploy)
- [Roll back](#roll-back)
- [Restore the database](#restore-the-database)
- [Rotate a key](#rotate-a-key)
- [Two-step key](#two-step-key)
- [Separate keys per copy](#separate-keys-per-copy)
- [Sign everyone out](#sign-everyone-out)
- [Turn off AI or email in an emergency](#turn-off-ai-or-email-in-an-emergency)
- [Turn a feature or gate on or off](#turn-a-feature-or-gate-on-or-off)
- [Shut down cleanly](#shut-down-cleanly)
- [Writing this month's world](#writing-this-months-world)
- [If something goes wrong: incident and breach response](#if-something-goes-wrong-incident-and-breach-response)
- [Move to Render](#move-to-render)
- [Uptime check](#uptime-check)
- [Launch week](#launch-week)
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
| The live app, after step 4 | Render (`render.yaml`), at go.northwend.app, deploying `main`, behind Cloudflare's proxy (`docs/CLOUDFLARE.md`). The move: [Move to Render](#move-to-render). |
| Database roles | One owner role for `northwend-migrate`, one for the app, one for the jobs, once `docs/DB_ROLES.md` is done. |
| The databases | Neon. One project or branch for live, one for staging. |
| Scheduled jobs | Render cron jobs in `render.yaml`: `northwend-prices` (every 15 minutes in market hours) and `northwend-news` (hourly). GitHub Actions, `.github/workflows/scheduled-sync.yml`: history, dividend dates, the tidy, the Monday email, walk reminders, Trail Conditions. |
| The app's settings | Streamlit: the app's menu > Settings > Secrets. Render: the service's Environment. |
| The jobs' settings | GitHub: the repo's Settings > Secrets and variables > Actions. Render's cron jobs: each job's Environment. |
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
- **Render cron jobs:** nothing to restart either. To run one now: the job's
  page > Trigger Run. Its run list shows each run and its log; a failed run
  also emails the admin.

---

## Calendar

What comes round on a date (PLAN "Alongside, any time"). Each line points
to its own steps; copy the dates into your own calendar too. Months, not
days, except where a day was set.

| When | What | How |
|---|---|---|
| Every quarter: January, April, July, October | The restore drill | [Restore the database](#restore-the-database), "Quarterly restore drill": a Neon branch of the live project from an hour ago, then `python scripts/restore_check.py --db ask --against ask` (counts only, read-only; strings typed without being shown). No table missing, no fewer rows in the core tables, differences only the last hour's. Delete the branch and add a line to the drill's table. |
| Yearly for each listed advisor, as each falls due | The license re-check | `licence_check.py`: a check is due 11 months after the last one, and the nightly tidy job emails the count each week while any are due. Admin > License checks lists them: look each advisor up again on FINRA BrokerCheck or the SEC's IAPD and record the source, the CRD and the day. Past 13 months an advisor is left out of the directory until re-checked. |
| January | Dated yearly figures | Review dated yearly figures in season content, and anything else that names a year's figure (contribution limits, for one), against the new year's official numbers. Update them, and add a What's new entry if people will notice. |
| October, with that quarter's drill | Key rotation | [Rotate a key](#rotate-a-key), one key at a time: `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `FINNHUB_API_KEY`, the Neon password; live and staging each their own. `NORTHWEND_TOTP_KEY` only through [Two-step key](#two-step-key). Any key that may have been seen is rotated at once, whatever the month. |
| November 6, 2026 | Retire the old Streamlit Community Cloud app | [Move to Render](#move-to-render), step 9: nobody is still opening the old address, then delete the old live app on Community Cloud (keep the staging app) and move the Streamlit line in the [Monthly budget](#monthly-budget). Then tick ROADMAP 4.8. |
| Every month, early in the month, if `month_world` is on | Write this month's world | [Writing this month's world](#writing-this-months-world): last month's past facts in plain words, official sources, reviewed before `reviewed_on` is set; Tests, then staging and release. Skipping a month is fine - nothing shows that month. |
| Every month | The budget | [Monthly budget](#monthly-budget): fill in the amounts and compare them with seat revenue. |
| Whenever something isn't working as usual | The website's status page | `STATUS_NOW` in `website/build.py` says what, plainly, and what still works; once it's fixed, back to "All systems normal" with a dated line in `NOTICES` (past notices, newest first). `python website/build.py`, then through staging and release as usual. No figures about people, no uptime percentages. |

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
   the repo on your computer (it needs only `pip install "psycopg[binary]==3.3.6"`,
   not all of `requirements.txt`):

   ```
   python scripts/restore_check.py --db ask --against ask
   ```

   `ask` asks for each connection string without showing it - first the new
   branch's, then live's - so the password never lands in PowerShell's
   history (pasting the strings on the command line would put them there).
   It lists every table in `schema_pg.sql` with both counts and the
   difference, and says if a table is missing from either. It only reads:
   the session is read-only, it never sets the schema up, and it never
   prints the connection strings. Counts only - nobody reads anyone's
   holdings to check a restore.

   **Reading it.** The difference is live's count minus the branch's: `+5`
   means live has 5 more rows. A missing table is a fail (it exits with 1).
   Fewer rows are **not** a fail by themselves - the script exits with 0 -
   so read its last lines: it lists every table with fewer rows on live.
   Restoring after a problem, that's what you expect (the branch is from
   before the rows were lost). In the drill, live should have **at least**
   as many rows as an hour-old branch in `users`, `positions`, `snapshots`,
   `plans` and `advisor_notes`; fewer there, beyond someone deleting their
   account in that hour, is a fail - write it down and find out why. (No Python to hand? In Neon's SQL Editor on
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
      `python scripts/restore_check.py --db ask --against ask` (the drill
      branch first, then live; typed without being shown).
      Passes when: no table missing; no "look at these" line naming `users`,
      `positions`, `snapshots`, `plans` or `advisor_notes` (beyond an account
      deleted in that hour); the other differences are small and positive
      (a few sign-ins, prices, sessions).
- [ ] Minutes from start to counts: ____ (almost all of it is the Neon
      console; the count itself takes under a second)
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
| `POLYGON_API_KEY` | polygon.io (also massive.com) > Dashboard > API Keys - the free plan | The `POLYGON_API_KEY` GitHub secret (the nightly dividend dates job), Render (only so Admin > System says it's set) | Actions > Scheduled sync > Run workflow: the dividend-dates job is green and prints how many it asked. Without it the job fetches nothing and says so; the pages still show Yahoo's and the brokerage file's dates. |
| `NORTHWEND_TOTP_KEY` | Made on your computer (see [Two-step key](#two-step-key)) | App settings (live and staging each their own), Render. Not in GitHub. A copy in your password manager. | Never just replace it: the old one must stay behind the new one until everything is re-encrypted. Follow [Two-step key](#two-step-key), "Rotate it". |
| The Neon password (inside `PORTFOLIO_DB` and `DATABASE_URL`) | Once the roles are split: `northwend-migrate --db "<owner string>" --roles --new-password northwend_app` (or `northwend_jobs`), which prints the new string once (`docs/DB_ROLES.md`, "A new password for a role"). The owner's own: Neon console > the project > Roles > `neondb_owner` > Reset password. | The app role's: `PORTFOLIO_DB` in the app's settings (Render web; staging's Secrets). The jobs role's: Render's two cron jobs' `PORTFOLIO_DB` and the `DATABASE_URL` GitHub secret. The owner's: your password manager only. | The old password stops at once, so the app (or the jobs) are down until the new string is in. Do it at a quiet hour, all places in one go. Restart the app. Run the workflow. |
| GitHub | - | Holds copies of the keys above, not keys of its own | If GitHub itself may be exposed: change the password, check two-factor is on, delete unused personal access tokens, review which apps have access (Streamlit, Render), then rotate every key above, since a changed workflow could have read any secret. |
| Paddle keys (step 6) | Paddle dashboard: the API key, and any notification secret | Render's Environment and the GitHub secret for the reconciliation job. Staging gets sandbox keys only. | Restart the app. Run the reconciliation job. A test will fail on a live billing key in the repo (coming in this step, PLAN 1b.4). |

`ALERT_EMAIL`, `APP_URL`, `NORTHWEND_ADMINS`, `NORTHWEND_GATES` and
`NORTHWEND_FLAGS` aren't secrets, but they live in the same places.

---

## Two-step key

Audit 1.1e. The key each person's authenticator app uses is stored in the
database (it's needed to check their codes, so it can't be hashed). With
`NORTHWEND_TOTP_KEY` set in the app's settings, those keys are stored
encrypted, so a copy of the database alone can't make anyone's codes. Without
it they are stored readable, as before - fine for a local copy. Admin >
System shows the key as set or not (with a short key id, never the key) and
how many two-step keys are encrypted, still readable, or won't open.

**Losing the key locks every app code out** (backup codes and the password
still work, and Admin > Reset two-step sign-in is the way back for anyone
stuck). Keep a copy of each key in your password manager before putting it
anywhere else.

**Turn it on (once per copy: staging first, then live).** In this order:
1. Make a key on your computer:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
   Save it in your password manager, named for the copy (staging and live
   each get their own).
2. Put it in the app's settings as `NORTHWEND_TOTP_KEY` (Streamlit: Secrets;
   Render: Environment) and restart.
3. Admin > System: "Two-step key: set (key id ...)". Write the key id down.
   New setups are encrypted from now on, and each older one is encrypted the
   next time its owner signs in with a code.
4. Encrypt the rest now, from your computer, with the same key in the shell
   (only the environment is read, never `.env`):
   `NORTHWEND_TOTP_KEY="<the key>" python manage_users.py --db "<that copy's connection string>" encrypt-two-step`.
   It prints the key id it used: it must match step 3. It refuses, changing
   nothing, if anything is already encrypted with a different key.
5. Admin > System: "Two-step keys stored: N encrypted, 0 readable". The
   admin action log shows the command.
6. Only now, for the live copy: in `disclosures.py` set
   `TWO_STEP_ENCRYPTED = True` (the in-app Security section, the About page
   and the Privacy Policy then say the keys are stored encrypted), run
   `python website/build.py`, and commit through staging and release. Not
   before step 5 shows 0 readable on the live app: the published words must
   be true when they go out.

**Rotate it** (it may have leaked, or it lived on a host you're leaving):
1. Make a new key (step 1 above).
2. In the app's settings: the new key, a comma, then the old one
   (`NORTHWEND_TOTP_KEY = "<new>,<old>"`), and restart. The first key
   encrypts; both open.
3. From your computer, with the same two keys in the shell:
   `NORTHWEND_TOTP_KEY="<new>,<old>" python manage_users.py --db "..." encrypt-two-step --rotate`.
4. Admin > System: none "with an older key". Then set the setting to the new
   key alone, restart, and check System shows nothing that "won't open".
   Keep the old key in your password manager while any backup from before
   the rotation is kept: a restore brings back rows encrypted with it (put
   it back behind the new one, then `--rotate` again).

**If System shows keys that "won't open":** the setting holds a different
key from the one they were encrypted with. Put the right key back (or in
front, comma-separated) and restart; nothing was lost. Meanwhile those
people can sign in with a backup code, and the admin is emailed (an error
named KeyUnreadable, at most once an hour). If the key is truly lost: each
of them needs Admin > Reset two-step sign-in, then sets it up again.

---

## Separate keys per copy

PLAN step 4.5 (audit 1.5c). The live copy has keys of its own, made for it
and kept nowhere else: never one shared with staging, your computer, the AI
eval or the old Community Cloud app. Then a key that leaks from staging (or a
laptop) can't reach live people's data, live's AI bill or live's email
reputation, and each copy's key can be rotated without touching the other.

Do it once, at a quiet hour, after the move to Render (or as part of its
step 1). For each row: make the new key, put it in every place in the
"Live copy" column, check it, then revoke the old one if it was shared. Name
each key for its copy ("northwend-live", "northwend-staging") wherever the
service lets you, and keep a copy in your password manager under the same
name.

| Key | Make the live copy's own at | Live copy: where it goes | Staging gets | Check it worked |
|---|---|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com > Settings > Workspaces: a "Northwend production" workspace (and set its monthly spend limit at or just above `NORTHWEND_AI_CEILING_USD`), then API keys > Create key in that workspace | Render web service `northwend` only. Not the cron jobs, not GitHub. | Its own key from a "Northwend staging" workspace, in staging's Streamlit Secrets | Admin > System: AI key set. Ask Northwend one question. Anthropic console > Usage shows it under the production workspace only. `AI_ZDR` stays 0 unless Anthropic's written zero-retention confirmation covers this workspace. |
| `RESEND_API_KEY` | resend.com > API Keys > Create: "Sending access", domain northwend.app, named northwend-live | Render web, both Render cron jobs (their failure email), the `RESEND_API_KEY` GitHub secret | No key and `MAIL_DRY_RUN` = 1 (or its own sending-only key, named northwend-staging) | Admin > System: email is sending. Ask for a password reset to your own address: it arrives. Resend > Emails shows it delivered. |
| `FINNHUB_API_KEY` | finnhub.io's free plan shows one key per account (if its Dashboard now offers a second key, use that instead): register a second free account for the live copy (with an address you own, e.g. the one for operations) and copy its key from the Dashboard | Render web (the in-app refresh), both Render cron jobs, the `FINNHUB_API_KEY` GitHub secret | The existing key, in staging's Secrets (its minute limit is then no longer shared with live) | `northwend-prices` > Trigger Run: green. A ticker's page on the live app shows a price time from today. |
| `POLYGON_API_KEY` | polygon.io (also massive.com) > Dashboard > API Keys > New key, named northwend-live (the free plan) | The `POLYGON_API_KEY` GitHub secret (the nightly dividend-dates job); Render web only so Admin > System says it's set | Nothing (staging has no jobs) | Actions > Scheduled sync > Run workflow: the dividend-dates job is green and prints how many it asked. Then revoke the old key. |
| `NORTHWEND_TOTP_KEY` | Made on your computer ([Two-step key](#two-step-key), step 1). **Never just swapped:** live's existing two-step keys are encrypted with the current one. If live's current key was ever on staging, your computer's `.env`, or Community Cloud, follow "Rotate it": the new key, a comma, the old one in Render; `manage_users.py encrypt-two-step --rotate` with both keys in the shell and live's app-role string; then the new key alone. | Render web only. Not the cron jobs, not GitHub. | Its own key, made separately, in staging's Secrets | Admin > System: "Two-step key: set (key id ...)" matching the id you wrote down for live, "0 readable", none "with an older key", none "won't open". Sign in with an app code. |
| Live database, app role (`PORTFOLIO_DB`) | `northwend-migrate --db "<live owner string>" --roles` prints it once (`docs/DB_ROLES.md`) | Render web: `PORTFOLIO_DB`, with `NORTHWEND_SKIP_SCHEMA_SETUP` = 1 | Staging's own Neon project and its own app-role string | DB_ROLES step 2's check; Render > Logs clean; save a watchlist ticker. |
| Live database, jobs role (`PORTFOLIO_DB` / `DATABASE_URL`) | The same command, the same time | Render cron jobs `northwend-prices` and `northwend-news`: `PORTFOLIO_DB` (with `NORTHWEND_SKIP_SCHEMA_SETUP` = 1); the `DATABASE_URL` GitHub secret (with the repository variable `NORTHWEND_SKIP_SCHEMA_SETUP` = 1) | Its own, kept for checks by hand | Trigger Run on both cron jobs; Actions > Scheduled sync > Run workflow: every job green. |
| Live database owner | Neon > the live project > Roles > `neondb_owner` > Reset password (DB_ROLES step 5), after the two above are in | Your password manager only; pasted into `northwend-migrate` when the schema changes | Staging's owner, reset the same way | The old owner string no longer connects. The app and the jobs still work (they don't use it). |
| Paddle keys (PLAN step 6, not yet) | Paddle dashboard, live mode | Render web, the reconciliation job's GitHub secret | Sandbox keys only | The reconciliation job runs green. |

Not secrets, but per copy and set in the same places: `ALERT_EMAIL`,
`APP_URL` (live: https://go.northwend.app/), `NORTHWEND_ADMINS`,
`NORTHWEND_GATES`, `NORTHWEND_FLAGS`, `NORTHWEND_AI_CEILING_USD`, `AI_ZDR`,
`MAIL_DRY_RUN` (live 0, staging 1), `NORTHWEND_ENV` (live production, staging
staging) and `NORTHWEND_SKIP_SCHEMA_SETUP`. The eval's key
(`ANTHROPIC_API_KEY_EVAL`) is the eval workspace's own, only ever in your
shell for `python -m evals.run` - never the live key, never in an app.

Done when:
- [ ] Every row above is ticked for the live copy, and no key in Render or
      GitHub is also in staging's Secrets, the old Community Cloud app or a
      `.env` file.
- [ ] Admin > System on the live app shows every key set, and on staging
      shows staging's own (a different two-step key id).
- [ ] Each shared key that was replaced is revoked at its service.

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

When a flag or gate changes on **live**, also change `LIVE_FLAGS` /
`LIVE_GATES` in `website/build.py`, run `python website/build.py` and release:
the website's What's new page announces exactly what's on for everyone.

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
   point go.northwend.app at a page on the website that says Northwend has
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

## Writing this month's world

The monthly note inside the drill card on Home (`month_world.py`, flag
`month_world`; ROADMAP Phase C). Northwend ships the frame only: every note
is the owner's, written by hand and reviewed (L3) before it shows. A month
with no note shows nothing - skipping one is fine.

1. **Write it** early in the month, about last month, as a new entry at the
   top of `NOTES` in `month_world.py`:

   ```python
   {"month": "2026-11",                      # the month it shows in (and the next)
    "title": "October in plain words",
    "paragraphs": [                           # 2 to 4 short paragraphs, past facts only
        "...", "..."],
    "for_mix": {                              # any of stocks, bonds, cash; the app
        "stocks": "Last month, stock prices ...",   # puts "For someone with mostly
                                              # stocks (about 72% of your mix):" first
        "bonds": "...", "cash": "..."},
    "sources": [("Consumer Price Index, October", "https://www.bls.gov/...")],
    "reviewed_by": "",                        # filled in at step 3
    "reviewed_on": ""},
   ```

2. **The rules** (the checks enforce the words; the rest is on you):
   - Past facts only - what happened, never what comes next or what to do.
   - Never these words: will, won't, going to, expect, forecast, predict,
     outlook, should, best, recommend, buy, sell, "now is".
   - No tickers, fund names or fund families, no brokerages. Capitals like
     CPI, GDP, FOMC, US are fine (`month_world.ACRONYMS`); add one there only
     if it's a measure or an agency.
   - Sources: official or primary sites only (`month_world.OFFICIAL_SITES`:
     federalreserve.gov, bls.gov, bea.gov, treasury.gov, treasurydirect.gov,
     sec.gov, investor.gov, fdic.gov), `https://` addresses.
   - The per-class lines say what happened to that kind of holding, never
     what someone with it should do. There's no US / international line:
     Northwend has no data to pick it.
3. **Get it reviewed** (L3, docs/LEGAL_GATES.md section 6) before it's
   published. Then fill in `reviewed_by` (who) and `reviewed_on` (the day,
   `2026-11-03`). Without both it never shows.
4. **Run the tests**: `python -m unittest tests.test_month_world` - every
   note in `NOTES` goes through the same checks, so a banned word, a ticker
   or an unofficial source fails here (and in Tests) before it ships.
5. **Release** as usual: commit on `staging`, check the card on the staging
   copy (Home, the drill card - `month_world` and `drills` on), then release
   to main. People who turned on Trail Conditions get one fixed line saying
   there's a new note, once.

Old notes can stay in `NOTES` (they stop showing after the month after
theirs) or be removed.

---

## If something goes wrong: incident and breach response

For anything that may have exposed, changed or lost people's data: a leaked
key or password, someone seeing an account that isn't theirs, data sent to
the wrong person, a stolen laptop with a connection string on it, or a
provider telling you they were breached. For a plain outage or a bad deploy,
use [Roll back](#roll-back) or [Restore the database](#restore-the-database)
instead.

Stay calm and keep to what's true. Say only what you know. Write down times
(UTC) and what you did as you go, from the first minute: a plain text file
on your own computer is fine. It becomes the incident record.

### 1. Tell what happened

Look in these places. Read counts, kinds and times - never anyone's
holdings or figures.

| Where | What it tells you |
|---|---|
| Error alert emails (to `ALERT_EMAIL`) | A kind of error and where in the code, at most once an hour per kind (`error_alerts.py`). A sudden new kind, or a failed scheduled job, is often the first sign. |
| Admin > System | This copy's version, database, email status, which keys are set (never their values), flags and gates, the limits on uploads and saves, recent errors, and the admin action log. |
| The admin action log (Admin > System, last 100 rows; `admin_log` table) | Every admin action in the app and every changing `manage_users.py` command: when, which admin, which account. An action nobody remembers taking is a red flag. |
| The host's logs | Streamlit Cloud: the app's "Manage app" log. Render (after the move): the service's Logs and Events. Full error details live here, not in the alerts. |
| Cloudflare (after the move) | Security > Events and Analytics: unusual traffic, blocked requests, where it came from. |
| Neon | The project's Monitoring (connections, load) and its operations list (branches made, passwords reset). |
| GitHub | Actions run history (a workflow you didn't run or change), Settings > Security log, deploy keys and the apps with access. |
| Provider consoles | Anthropic usage (a spend spike), Resend's email log (emails you didn't expect), Finnhub usage. |

Then decide: is people's data involved (who could have seen or changed
what), or is it only a service problem? If unsure, treat it as a breach
until you know otherwise.

### 2. The first hour: contain

Do what fits; when in doubt, do more.

1. **Sign everyone out.** Admin > System > "Sign everyone out", or
   `python manage_users.py --db "<live connection string>" sign-out-all`.
   Every open tab and every "stay signed in" device has to sign in again
   ([Sign everyone out](#sign-everyone-out)).
2. **Rotate the keys involved** - all of them if unsure
   ([Rotate a key](#rotate-a-key)): `ANTHROPIC_API_KEY`, `RESEND_API_KEY`,
   `FINNHUB_API_KEY`, the Neon database password (inside `PORTFOLIO_DB` and
   `DATABASE_URL`), and `NORTHWEND_TOTP_KEY` (the key the two-step secrets
   are locked with - follow its own section in this runbook, since a new key
   has to re-lock the stored secrets). Staging's keys are separate: rotate
   them too if staging could be involved.
3. **Turn off what's leaking.** A feature by flag
   ([Turn a feature or gate on or off](#turn-a-feature-or-gate-on-or-off)),
   AI or email ([Turn off AI or email in an emergency](#turn-off-ai-or-email-in-an-emergency)),
   or the jobs (GitHub Actions > Scheduled sync > Disable workflow). One
   account: `manage_users.py passwd <login>` or `reset-two-step <login>`.
4. **Take the app offline if you must.** There is no maintenance page yet.
   The choices, quickest first: stop the app (Render: the service's
   Settings > Suspend; Streamlit Cloud: a reboot isn't enough - delete the
   app from its menu, and deploy it again from GitHub afterwards);
   or remove `PORTFOLIO_DB` from the app's settings and restart - a hosted
   copy without its database stops at a calm "isn't set up" page before it
   touches any data (`settings.config_problem()`). `MOVED_TO` is for a real
   move, not an outage: it tells people their account is somewhere else.
   Say so on the website's status page (northwend.app/status, `STATUS_NOW`
   in `website/build.py`; see the [Calendar](#calendar)) - plainly, with
   no guesses about the cause.
5. **Keep the evidence.** Don't clear error records, the admin log or the
   host's logs. If a database copy helps, make a Neon branch at the current
   time; it holds personal data, so delete it once the incident is closed.
6. **Undo damage.** If data was changed or deleted, restore from a Neon
   branch at a time before it started
   ([Restore the database](#restore-the-database)). The window is short
   (about 6 hours today), so start this early.

### 3. Work out the facts

Which accounts, and how many. Which kinds of data, and for how long it was
open. Counts and kinds, not anyone's figures.

- What Northwend holds: logins and emails, holdings (symbols, shares, cost,
  value, cash), activity, plans and profile answers, advisor notes,
  proposals and reports, and two-step secrets (locked with
  `NORTHWEND_TOTP_KEY`).
- What it never holds: brokerage logins, full account numbers (only the
  last 3 digits), uploaded files. Passwords and backup codes are stored only
  as hashes; "stay signed in" tokens and email links too.
- Whether advisors' clients are among them, and which advisors.

### 4. Who to tell, and how fast

The legal deadlines below are **check with a lawyer** - this page doesn't
decide them. Call the lawyer first; they say which laws apply and by when.

1. **The lawyer, the same day.** Every US state has a breach-notification
   law. Most require telling affected residents, and some set a deadline
   (often in the range of 30 to 60 days; check with a lawyer for each state
   involved). Some also require telling the state attorney general, or the
   credit bureaus, once a number of residents is passed. Which data counts
   (an email and password together often does) differs by state. Check with
   a lawyer.
2. **The cyber insurer, once there is one.** Policies usually need prompt
   notice, often before you hire anyone; read the policy's notice clause.
3. **Advisors whose clients are affected**, within the time the advisor
   security page promises (still a draft: the lawyer sets it), so they can
   meet their own duties to their clients and their firms (Regulation S-P
   and state rules; check with a lawyer). Tell the advisor, and their firm's
   compliance contact if they gave one.
4. **Affected people, by email, "without unreasonable delay"** - the
   Privacy Policy's promise (section 9): by email where there's an address,
   in the app, and as the law requires. Don't wait for every detail; send
   what's known and follow up. Many state laws allow a delay only when law
   enforcement asks for one in writing - check with a lawyer.
5. **Providers involved** (Neon, Streamlit or Render, Resend, Anthropic,
   Cloudflare) if the problem came through them or they need to act.

Send people's emails from Resend to each person (never one email with
everyone in To or Cc). No figures, no holdings, no account details in them -
the same rule as every Northwend email.

### 5. The email to affected people

Plain words, short. Fill in the brackets; cut a line that isn't true.

> **Subject:** About your Northwend account: a security problem
>
> Hello,
>
> We're writing to tell you about a security problem that affected your
> Northwend account.
>
> **What happened.** On [date], we found that [plain description - e.g.
> "someone was able to see other people's accounts for about two hours"].
> It started on [date] and was stopped on [date].
>
> **What was involved.** [The kinds of information - e.g. "your email
> address and the list of investments you entered"]. It did not include
> [what wasn't involved - e.g. "your password, which we store only in a
> scrambled form"]. Northwend never holds your brokerage login or full
> account numbers.
>
> **What we've done.** [e.g. "We closed the gap, signed everyone out and
> changed our keys."]
>
> **What you can do.** Sign in again and choose a new password - and change
> it anywhere else you used the same one. Turn on two-step sign-in on the
> Account page. Be wary of emails asking for your password or brokerage
> login: Northwend never asks for them.
>
> **Questions.** Reply to this email or write to support@northwend.app.
> We'll write again if we learn more.
>
> We're sorry this happened.
>
> [Name], Northwend

Have the lawyer read it before it goes: some states require particular
content.

### 6. Afterwards: the post-incident checklist

- [ ] Every key that could have been seen is rotated, and the old ones are
      revoked.
- [ ] The cause is fixed, on staging first, with a test that would have
      caught it.
- [ ] Every notice the lawyer listed is sent, with the date of each.
- [ ] Any Neon branch made for evidence or restore is deleted (it holds data
      people may since have deleted).
- [ ] Anything turned off (a flag, AI, email, the jobs, the app) is back on,
      or the reason it stays off is written down.
- [ ] The incident record says what happened, how it was found, how long it
      was open, who was told and when, and what changed. Keep it with the
      business records.
- [ ] This runbook, `docs/SECURITY_AUDIT.md` and, if a promise changed, the
      Privacy Policy are updated.
- [ ] A What's new entry if people should know what changed for them.
- [ ] The website's status page is back to "All systems normal", with a
      dated line in `NOTICES` (`website/build.py`).

---

## The second-walk measure

The one retention measure (R1, `feature_counts.py`): of the people who
finished a first monthly walk at least 46 days ago (their 45 days are over),
how many finished a second within 45 days of the first (day 45 counts).
Left out: anyone with "Leave me out of feature counts" on, anyone whose
first walk was a check-in from before walks were counted, and admin logins
(`users.is_admin` and `NORTHWEND_ADMINS`). Deleted accounts take their
settings with them. Nothing shows for a group under 20.

**Where to see it:** Admin > Feature tests, "The monthly walk": "Walked again
within 45 days: X of Y (Z%)", with "target N%" beside it once
`NORTHWEND_SECOND_WALK_TARGET` is set (a percent, in the host's settings), and
"By the month of the first walk" (a month under 20 shows "fewer than 20"; a
month can also be held back so the small ones can't be worked out by
subtraction).

**The same number by hand**, read-only, in the Neon console's SQL editor
(it returns totals only, and no row at all under 20 first walks; its "today"
is the database's date, UTC on Neon, like the app's). Put your admin logins
from `NORTHWEND_ADMINS` in the commented line. The Admin page is the place to
read it - the Privacy Policy says counts are shown only there; this is for
checking it.

```sql
WITH people AS (
  SELECT p.user_id AS who, p.data::jsonb AS d
  FROM user_prefs p JOIN users u ON u.id = p.user_id
  WHERE p.data LIKE '%"walk_verdicts"%' AND COALESCE(u.is_admin, 0) = 0
  -- AND lower(u.username) NOT IN ('your-admin-login')
), counted AS (
  SELECT who, d FROM people
  WHERE jsonb_typeof(d->'walk_verdicts') = 'object'
    AND COALESCE(d->'feature_counts_off' IN ('false', 'null', '0', '""', '[]', '{}'), true)
), walk_days AS (
  SELECT c.who, c.d, left(e.v->>'on', 10)::date AS day
  FROM counted c CROSS JOIN LATERAL jsonb_each(c.d->'walk_verdicts') AS e(m, v)
  WHERE jsonb_typeof(e.v) = 'object' AND e.v->>'on' ~ '^\d{4}-\d{2}-\d{2}'
), ranked AS (
  SELECT who, d, day, row_number() OVER (PARTITION BY who ORDER BY day) AS n
  FROM walk_days
), firsts AS (
  SELECT who, d, max(day) FILTER (WHERE n = 1) AS first_on,
         max(day) FILTER (WHERE n = 2) AS second_on
  FROM ranked GROUP BY who, d
), eligible AS (
  SELECT * FROM firsts f WHERE NOT EXISTS (
    SELECT 1 FROM jsonb_array_elements(CASE jsonb_typeof(f.d->'checkin_log')
           WHEN 'array' THEN f.d->'checkin_log' ELSE '[]'::jsonb END) AS l(m)
    WHERE jsonb_typeof(l.m) = 'string'
      AND (l.m #>> '{}') COLLATE "C" < to_char(f.first_on, 'YYYY-MM') COLLATE "C")
), totals AS (
  SELECT count(*) AS first_walks,
         count(*) FILTER (WHERE first_on + 45 < current_date) AS window_closed,
         count(*) FILTER (WHERE first_on + 45 < current_date
                          AND second_on <= first_on + 45) AS second_walks
  FROM eligible
)
SELECT first_walks, window_closed,
       CASE WHEN window_closed >= 20 THEN second_walks END AS second_walks,
       CASE WHEN window_closed >= 20
            THEN round(100.0 * second_walks / window_closed) END AS percent
FROM totals WHERE first_walks >= 20;
```

By the month of the first walk: the same query with its last part
(`totals` and the final `SELECT`) replaced by this. It shows only months of
20 or more whose every window is over; Admin may also hold one back, so
use it only beside the total above.

```sql
SELECT to_char(first_on, 'YYYY-MM') AS month, count(*) AS people,
       count(*) FILTER (WHERE second_on <= first_on + 45) AS walked_again
FROM eligible
WHERE (date_trunc('month', first_on) + interval '1 month' - interval '1 day')::date + 45
      < current_date
GROUP BY 1 HAVING count(*) >= 20 ORDER BY 1;
```

On a local SQLite copy (`sqlite3 scratch.db`, never the real `portfolio.db`):

```sql
WITH people AS (
  SELECT p.user_id AS who, p.data AS d
  FROM user_prefs p JOIN users u ON u.id = p.user_id
  WHERE p.data LIKE '%"walk_verdicts"%' AND COALESCE(u.is_admin, 0) = 0
  -- AND lower(u.username) NOT IN ('your-admin-login')
), counted AS (
  SELECT who, d FROM people
  WHERE json_valid(d) AND json_type(d, '$.walk_verdicts') = 'object'
    AND NOT COALESCE(json_extract(d, '$.feature_counts_off') NOT IN (0, '', '[]', '{}'), 0)
), walk_days AS (
  SELECT c.who, c.d, substr(json_extract(e.value, '$.on'), 1, 10) AS day
  FROM counted c, json_each(c.d, '$.walk_verdicts') AS e
  WHERE e.type = 'object'
    AND date(substr(json_extract(e.value, '$.on'), 1, 10))
        = substr(json_extract(e.value, '$.on'), 1, 10)
), ranked AS (
  SELECT who, d, day, row_number() OVER (PARTITION BY who ORDER BY day) AS n
  FROM walk_days
), firsts AS (
  SELECT who, d, max(CASE WHEN n = 1 THEN day END) AS first_on,
         max(CASE WHEN n = 2 THEN day END) AS second_on
  FROM ranked GROUP BY who, d
), eligible AS (
  SELECT * FROM firsts f WHERE NOT EXISTS (
    SELECT 1 FROM json_each(f.d, '$.checkin_log') AS l
    WHERE json_type(f.d, '$.checkin_log') = 'array' AND l.type = 'text'
      AND l.value < substr(f.first_on, 1, 7))
), totals AS (
  SELECT count(*) AS first_walks,
         coalesce(sum(date(first_on, '+45 days') < date('now')), 0) AS window_closed,
         coalesce(sum(date(first_on, '+45 days') < date('now')
                      AND second_on <= date(first_on, '+45 days')), 0) AS second_walks
  FROM eligible
)
SELECT first_walks, window_closed,
       CASE WHEN window_closed >= 20 THEN second_walks END AS second_walks,
       CASE WHEN window_closed >= 20
            THEN round(100.0 * second_walks / window_closed) END AS percent
FROM totals WHERE first_walks >= 20;
```

`tests/test_second_walk_measure.py` runs the SQLite query against the code's
own count; `tests/test_postgres.py` does the same for the Postgres one.

---

## App use (analytics)

`analytics.py`, flag `analytics`, off unless set. Events (a page opened, holdings
added with the way only, a walk finished, a decoder used, first steps done or
skipped, a question asked - a count, a challenge started, a drill rehearsed) go
into Northwend's own database, table `analytics_events`: no new service, no
script on any page, no cookie, no cost. Each row: when, a random ID kept in the
person's settings (`analytics_id` - never the user id), the event, the page and
a few fixed words (the kind of device). Nothing else gets through
`analytics.clean`.

**Before turning it on:** publish the revised Privacy Policy first
(`docs/legal/next/privacy-policy.md`: it says app events are recorded, names the
service as "Northwend's own database" and adds the 12-month row) with its new
effective date (`disclosures.LAST_UPDATED`), and the About page's wording to
match. Only then add `analytics` to `NORTHWEND_FLAGS`. With the flag on, the
Account switch reads "Don't use my data to improve the app" (the same setting,
`feature_counts_off`, so earlier choices carry over); with it off it keeps the
published name "Leave me out of feature counts".

Never recorded: the flag off; the switch on; a browser sending Global Privacy
Control (`Sec-GPC: 1`) or Do Not Track (`DNT: 1`); admins; an advisor in a
client's account; anyone not signed in. Turning the switch on deletes that
person's past events and their ID at once (a new ID if they turn it off again);
deleting an account does the same, before its settings go. Kept 12 months:
`tidy.py` prunes nightly ("app-use events"). A person's own events are in their
Export everything (`app_use.csv`).

**Where to see it:** Admin > App use (last 30 days): per event, per page and
people per day - each row only for 20 or more different IDs. There is no view of
one ID's events and nothing by advisor; it is never used to choose, rank or
suggest an advisor (docs/DIRECTION_2026-10-09.md).

**To turn it off:** take `analytics` out of `NORTHWEND_FLAGS` - recording stops
on the next page change. To delete everything: `DELETE FROM analytics_events;`.

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
Community Cloud to Render, at go.northwend.app, behind Cloudflare. The code
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
      `FINNHUB_API_KEY`, `POLYGON_API_KEY`, `NORTHWEND_ADMINS`, `ALERT_EMAIL`,
      `NORTHWEND_GATES` (today `L0`), `NORTHWEND_FLAGS`,
      `NORTHWEND_AI_CEILING_USD`. `NORTHWEND_SKIP_SCHEMA_SETUP`: `0` until
      the database roles are split (`docs/DB_ROLES.md`), then `1` - on the
      web service and both cron jobs. The live copy's own keys, not
      staging's: [Separate keys per copy](#separate-keys-per-copy).
      `AI_ZDR`: `0` until Anthropic has confirmed
      zero data retention in writing. `NORTHWEND_TOTP_KEY`: exactly the live
      app's (from your password manager) - a different one means nobody's
      app codes work on Render ([Two-step key](#two-step-key)). The rest (`NORTHWEND_ENV=production`,
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
      gates and flags match the live app's, and the two-step key has the
      live app's key id with none that "won't open".
- [ ] Render > Logs: no errors.

Emails sent from this copy already link to go.northwend.app (`APP_URL`),
which doesn't work yet; avoid sending any during the check.

Done when: all four are ticked.

### 3. Add the domain in Render
- [ ] The service > **Settings** > **Custom Domains** > **Add**:
      `go.northwend.app`. Render shows the `CNAME` target to use (the
      service's onrender.com name).

### 4. Cloudflare in front
- [ ] Follow `docs/CLOUDFLARE.md` sections 1 to 7, in order: the `app`
      record (DNS only until Render verifies, then Proxied), Full (strict),
      WebSockets, the "never cache" rule, the six security headers,
      Email Address Obfuscation and the other script features off, and the
      Render address turned off if offered.

Done when: Render shows `go.northwend.app` Verified with its certificate,
and the record in Cloudflare is Proxied.

### 5. Check go.northwend.app
- [ ] `docs/CLOUDFLARE.md` section 8: the pages work, the six headers are
      there, nothing is cached, health says `ok`.
- [x] securityheaders.com grade: A+ (aim: A). Date: October 6, 2026
- [ ] Sign up a test account with an address you own, confirm it, delete it
      (Account > Delete my account): sign-up, email links and the
      per-address limits work through the proxy.

Done when: all three are ticked.

### 6. Point everything at the new address
- [ ] The website's buttons: `APP_URL` in `website/build.py` to
      `https://go.northwend.app/`, `python website/build.py`, commit
      through staging and release (Cloudflare Pages redeploys the site).
- [ ] GitHub > Settings > Secrets and variables > Actions: the `APP_URL`
      secret to `https://go.northwend.app/` (links in the Monday email and
      the walk reminders).
- [ ] The uptime monitors ([Uptime check](#uptime-check)).

### 7. Turn the old app into a signpost
- [ ] Community Cloud > the live app > Settings > **Secrets**: delete
      everything, and add only `MOVED_TO = "https://go.northwend.app"`.
      Save. The old app needs no database or key for its "has moved" page,
      so none stays on Community Cloud.
- [ ] Open the old address with `?page=plan` on the end: it says Northwend
      has moved, and its button goes to `https://go.northwend.app/?page=plan`
      (old confirm and reset links in inboxes keep working that way).
- [ ] Recommended, since Community Cloud held them: rotate each key that
      lived there ([Rotate a key](#rotate-a-key)) at a quiet hour - the new
      ones go only to Render and GitHub. The Neon password goes with the
      database roles (`docs/DB_ROLES.md`, step 5). `NORTHWEND_TOTP_KEY`
      rotates its own way ([Two-step key](#two-step-key), "Rotate it").

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
- [ ] The app is served at go.northwend.app from Render behind Cloudflare,
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
2. **New monitor** > type **Keyword** (or **HTTP(s)** if the plan has no keyword
   type - the health check answers 200 only while the app is up), URL
   `https://go.northwend.app/_stcore/health`, keyword `ok` (alert when it's
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
| App (`/_stcore/health`) | UptimeRobot, October 6, 2026 | the owner's email |
| Website | UptimeRobot, October 6, 2026 | the owner's email |

---

## Launch week

What runs out first if many new people arrive in one day (50, 200, 1,000
sign-ups), what they see when it does, and what to change before marketing.
Worked out on October 7, 2026 from the code and from measurements on local
scratch copies - nothing live was loaded or called. Numbers with "about" are
estimates: check them against the dashboards listed at the end on the day.

### What runs out first

1. **Email (Resend free plan): at about 90 sign-ups in one day.** Each
   sign-up sends one confirm email, and the day's other emails (resets, error
   alerts, advisor requests) share the same 100. People can still sign up and
   use the app, but the AI features wait for a confirmed email.
2. **Live prices: fixed (October 7, 2026).** The minute-by-minute price
   check used to keep a database connection while it waited for another tab
   to fetch; at about 40 tabs open in market hours, pages failed with
   "Something went wrong". Now no connection is held while fetching and a tab
   that finds another one fetching skips that minute. In the same model, 40
   tabs: no page waited. What's left is freshness: with many different
   tickers, each is updated every 1-4 minutes instead of every minute (see the
   Live prices row).
3. **The server (Render Starter): at about 20-30 tabs open at once in market
   hours.** Every click gets slow. Memory lasts longer than the processor.
4. **Neon storage: at about 250 different tickers held** across all
   accounts, if the database is on Neon's free plan (0.5 GB).
5. **The AI ceiling: at about 200-300 people using the AI in a month**
   (about 70-100 if each uses their whole allowance), at the default $100.
6. **The app-wide sign-up cap: 200 accounts in one hour.** Only a sudden
   rush reaches it (a post that spreads, a mention in a newsletter).

The per-address limits can stop a group sooner: a class, an office or a
meetup on one wifi network is one internet address, and the fourth account
from one address in a day is turned away.

### Each limit

| Limit | Today | Set in | What a person sees | Hit at about | What to do |
|---|---|---|---|---|---|
| Sign-ups, whole app | 200 accounts an hour | `auth.SIGNUPS_PER_HOUR` | "Lots of people are signing up right now. Please try again in an hour." | 200 sign-ups in one hour. 1,000 in a day reaches it only if a fifth of them arrive in the same hour. | Keep it: it stops a script making accounts. If a planned event will bring more in an hour, raise it in code for that week. |
| Sign-ups, one internet address | 3 accounts a day, 10 tries an hour | `auth.SIGNUPS_PER_ADDRESS_PER_DAY`, `SIGNUP_TRIES_PER_ADDRESS_PER_HOUR` | "Too many new accounts from here for now. Please try again tomorrow." | The 4th person on one wifi network that day. Phone networks can share one address among many people. | Before a talk or class: ask people to sign up on phone data, or raise the daily number in code for that day. |
| Account emails, one internet address | 10 an hour (confirm, reset, new address together) | `auth.EMAILS_PER_ADDRESS_PER_HOUR` | "Too many emails asked for from here. Please try again in an hour." | Rarely: the sign-up limit above comes first. | Nothing. |
| Confirm emails, one email address | 1 every 2 minutes, 5 a day | `auth.CONFIRM_GAP_MINUTES`, `CONFIRMS_PER_DAY` | "We just sent one - check your inbox and spam folder. You can send another in a couple of minutes." / "That's a lot of emails for one day. Please try again tomorrow." | Only someone pressing Send it again many times. A send Resend refused no longer counts (`auth.send_failed`). | Nothing. |
| Resend's allowance | Free plan: 100 emails a day, 3,000 a month, and a limit on how many a second (check the Resend dashboard for the plan and its numbers) | The Resend account | The account is made and signed in; a yellow note says "We couldn't send the email just now. Please try again in a few minutes." The "Confirm your email" note with Send it again stays at the top. Until the email is confirmed, every AI feature says "Confirm your email to use this - open the link we sent you (you can send it again from the note at the top of the page)." Forgot password still answers "If there's an account for ..., we've sent it a link" but nothing arrives. | About 90 sign-ups in a day; about 2,500 in a month. | **Before marketing: a paid Resend plan** (no daily cap). Each refused email now shows in Admin > System as `EmailNotSent in dashboard.py` and is emailed to you once Resend accepts email again. Never-confirmed accounts are deleted after 30 days (`tidy.py`): after a day of refused emails, people who signed up then need to press Send it again. |
| The AI ceiling, whole app | `NORTHWEND_AI_CEILING_USD`; $100 a month when not set | Render's Environment | Nothing below 80%. From 80%: chat answers are shorter and "Reading screenshots is resting until November 1. Everything else in Northwend works as usual." (the same for the other optional helpers). From 95%: "Ask Northwend isn't starting new conversations until November 1. ..." At 100%: "Ask Northwend is resting until November 1. Everything else in Northwend works as usual." You get an email at 50% and at 80%. | About $0.30-0.50 a month for a typical active person, $1.00-1.50 at the most (their allowance plus the walk bonus). Only confirmed accounts use AI. So $100 covers about 200-300 typical people, or about 70-100 who use everything. A launch day where 200 people each ask a few questions: about $10-20. | Set the ceiling from the budget ([Monthly budget](#monthly-budget)) and the Anthropic console limit at about 1.5 times it. Watch Admin's AI panel the first week: its "projected" figure says where the month is heading. |
| AI allowance, one person | Individual chat $0.25 a day and $1.00 a month (about 15-20 and 75 messages); screenshot and CSV help $0.30 a month; an advisor $17 a month in all | `ai_usage.ALLOWANCES` | "About 12 messages left today", then "You've used today's messages. They start again tomorrow." or "... They start again on November 1." | Each person separately; it keeps one person's use small, not the total. | Nothing. |
| Anthropic's own limits | The console spend limit, and the account's rate limits (requests and tokens a minute, by usage tier) | The Anthropic console: Billing, and Settings > Limits | "Northwend is busy right now - try again in a minute." (rate limits), or "Ask Northwend isn't available right now." (the spend limit; you also get an error alert). The calm "resting" line in `docs/AI_COSTS.md` section 7.2 is not built for this case. | A new account's lowest tier allows only a few chat answers a minute. Many people chatting at once on launch day can reach it. | **Before marketing: check Settings > Limits.** Buying credit moves the account up a tier. Keep the console spend limit above the app's ceiling, so the ceiling's calm lines come first. |
| Database connections, the app | 5 per server process (one process today), each page waits up to 30 seconds for one | `pgcompat._pool_options` | After 30 seconds: "Something went wrong on this page. Try again, or open another page from the menu. ..." and you get an alert `PoolTimeout`. | A page uses a connection 6-11 times for a moment each (Home 9, Plan 11, measured). Clicks alone don't fill 5. The live-price check used to (it held one while it fetched); since October 7 it holds one only for a moment to read and a moment to write. | Nothing for the live-price check (done, next row). Use Neon's pooled connection string (the `-pooler` address, `docs/DB_ROLES.md`): Neon's own connection limit is then not a concern. |
| Live prices while a tab is open | Each open tab checks every minute; each ticker is fetched at most once a minute for everyone. One tab fetches at a time; a tab that finds another fetching skips that minute (no wait, no message) and leaves its tickers for the next fetch, which takes up to 20 of them after its own. No database connection is held while fetching. At most 50 Finnhub calls a minute for the whole app (Finnhub's free plan allows 60; 10 are left for the news box); past that, Yahoo, which is slower. | `live_prices.py` (`FINNHUB_PER_MINUTE`, `ASKED_PER_ROUND`), `LIVE_EVERY_SEC` in dashboard.py | Prices update later than "every minute" ("prices updated 2 min ago"). Nothing else: no waits, no errors. | Modelled on a scratch copy with the real price code (Finnhub 0.25 s, Yahoo 1 s, 3 people clicking, 5 minutes). Before the change: 15 tabs (120 tickers): clicks waited up to 30 seconds; 40 tabs (320 tickers): a fifth of the page loads failed after 30 seconds, and Finnhub refused about 200 calls. After: 5, 15 and 40 tabs: no click waited (page runs 0.2 s), no page failed, Finnhub refused none. Freshness: 5 tabs, every ticker within a minute; 15 tabs, half within 42 seconds and nearly all within about 2 minutes; 40 tabs, half within about 1.5 minutes and nearly all within 4-5 minutes (one fetch at a time does about 95 tickers a minute). The tab doing the fetch waits for it (up to about 25 seconds in the model). Shared tickers count once, so the same few funds held by everyone is far lighter. | Nothing before marketing. If prices lag too much on the day, decision D4 (a paid market-data plan) is the next step. |
| The 15-minute price job | Every ticker anyone holds, one a second (60 a minute) | `update_prices.DELAY` (1 second, the default; the workflow passes no `--delay`), `.github/workflows/scheduled-sync.yml` | Nothing directly: prices not refreshed keep their last value. | At about 700+ tickers not already fetched by the app in the last 10 minutes, a run takes longer than 15 minutes. While a run overlaps open tabs, the job and the app share the one Finnhub key: together they can pass 60 a minute, and the extra calls go to Yahoo (the app) or are retried in the next run (the job). | A paid market-data plan (D4) if runs grow long. If the repository is private, check GitHub Actions minutes too. |
| The nightly history job (Yahoo) | About 6 requests per ticker, 0.3 s apart | `sync_history.py`, the same workflow | Nothing directly. | About 3-5 seconds per ticker: 500 tickers is about 30-40 minutes. The job counts as failed whenever one ticker gets no data at all, so one mistyped symbol in anyone's holdings sends you "Sync price history failed" every night. | Read the run's log before acting on that email. Changing what counts as failed is a price-fetching change (plan first). |
| Neon (the database) | The restore window of about 6 hours suggests the free plan: 0.5 GB of storage and a monthly allowance of compute hours (check the Neon plan page) | The Neon project | When storage is full, saves fail ("... didn't work, so nothing was changed") and so do sign-ups. When compute hours run out, the whole app stops until the next month. | Price history takes about 2 MB per different ticker (minute-to-hourly bars), so about 250 tickers fill 0.5 GB. An app that is always open keeps the compute awake. | **Before marketing: a paid Neon plan** (it is needed for the 7-day restore window, D6, anyway). Look at Neon > Usage for storage and compute hours. |
| The server (Render Starter) | 512 MB of memory, half a processor, one process | `render.yaml` (`plan: starter`) | Pages take longer to draw after each click; prices lag. If memory runs out, Render restarts the app and every open tab reconnects. | Measured on a laptop: the app uses about 190-260 MB once loaded; each open tab keeps about 2-4 MB, plus about 11 MB while its page is drawn; one page draw takes about 0.6 seconds of processor time (expect 1-2 seconds on Starter). In market hours each open tab is redrawn once a minute when its prices change. So about 20-30 tabs open at once in market hours keep Starter busy all the time; memory lasts to about 60-80. | Standard (2 GB, 1 processor) is about twice the room: change `plan:` in `render.yaml` (through staging and release) or in Render's settings before marketing if more than about 20 people at a time are likely. More instances don't help: each tab's session lives in one process, and Render doesn't keep a visitor on one instance. Go up a size instead. |
| Error alert emails | At most one email an hour for each kind of error | `error_alerts.EVERY` | Nothing: people see the calm "Something went wrong" line. | A bad hour with five kinds of error is five emails. They go through Resend and use its allowance; when Resend refuses them, Admin > System still lists every kind. | Nothing. On launch day, look at Admin > System every few hours rather than waiting for email. |
| Uploads, saves and downloads, one login | 30/200, 60/300, 30/150 an hour/a day | `rate_limits.LIMITS` | "You've done a lot of that in a short time - please try again in a little while." | Never for a real person. | Nothing. |

### Before marketing: the owner's list

- [ ] Resend: a paid plan, or at least confirm the plan's daily number
      against the expected sign-ups. Fill in the Resend line in the
      [Monthly budget](#monthly-budget).
- [ ] Neon: a paid plan (also D6). Check storage and compute hours on Neon >
      Usage. `PORTFOLIO_DB` uses the pooled (`-pooler`) address.
- [ ] Anthropic: Settings > Limits shows a tier that allows more than a
      handful of chat answers a minute; the console spend limit is set; the
      app's ceiling is set in Render.
- [x] The live-price change above (not holding a database connection while
      fetching; skipping instead of waiting; at most 50 Finnhub calls a
      minute) - built October 7, 2026. Check it's released to main.
- [x] The 15-minute job keeps under Finnhub's 60 a minute (`update_prices.DELAY`
      is 1 second).
- [ ] Render: Standard, if more than about 20 people at a time are likely in
      market hours. Fill in the Render line in the budget.
- [ ] A test sign-up on go.northwend.app with your own address: the confirm
      email arrives (on a day the Resend allowance isn't used up).
- [ ] If a talk or class is the launch: decide about the 3-a-day limit per
      internet address.

### On the day

Look every few hours, counts only:
- Admin > System: new error kinds (`PoolTimeout`, `EmailNotSent`), the AI
  panel's percent and projection.
- Render > Metrics: processor near 100% for long stretches, or memory above
  about 400 MB on Starter, means it's time for Standard.
- Neon > Monitoring and Usage: connections, storage, compute hours.
- Resend's dashboard: emails sent today against the plan's number.
- The Anthropic console: usage today, and any rate-limit errors.

If something runs out: AI has its own calm lines and nothing else stops.
Email: a paid Resend plan takes effect at once; people press Send it again.
The server: change the Render plan (a new deploy, open tabs reconnect).
Prices: they keep their last value; nothing is lost.

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
- [ ] The advisor agreement text is final (no longer marked "beta"): the
      lawyer's wording in `advisor_agreement.TEXT`, `VERSION` bumped (every
      advisor is asked again), and the `advisor_agreement` flag on (staging
      first). Admin's accounts table shows who accepted which version.
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
      consent (built: `intros.SHARE_LINES` / `CONFIRM_LINE`, recorded by
      `intros.share_account`; the intro copy is `intros.COPY_STATUS` DRAFT -
      put the lawyer's words there, and turn on flag `intros` with `directory`).
- [ ] Consent records and advisor access logs are append-only and kept 7
      years (B6), and the Privacy Policy says so.
- [ ] The standing line "advice is the advisor's, not Northwend's", with
      name and firm, is on every advisor artefact (built with interim text:
      put the lawyer's wording in `standing_line.STANDING_LINE`).
- [ ] State coverage is handled as the attorney decided.
- [ ] The Terms no longer say Northwend "does not refer clients" (reworded
      by the attorney).
- [ ] License checks are stored, and the yearly re-check job runs (D15):
      built - the approval form records each check (`licence_check.py`),
      Admin > License checks lists those due, and the nightly tidy job's
      "Count advisors due a license check" step emails the count. Every
      advisor has a check on record (none shows "no check on record").
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
