-- Portfolio tracker schema (phase 1)
-- SQLite. Safe to run repeatedly; every object uses IF NOT EXISTS.

-- The schema's version (portfolio.SCHEMA_VERSION): one row, written by
-- portfolio._ensure_schema once the tables, back-filled columns and clean-ups
-- for that version are in. `northwend-migrate` runs it on purpose. Bump
-- SCHEMA_VERSION in the same change as any schema change.
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER NOT NULL,
    applied_at  TEXT    NOT NULL                 -- ISO 'YYYY-MM-DDTHH:MM:SSZ' UTC
);

-- Individual login accounts. Admin-provisioned only (see manage_users.py) -
-- there is no self-service signup anywhere in the app.
--
-- `user_id` on snapshots/positions/account_totals is declared directly
-- below (unlike live_price/day_open/realized_gain, which are ALTER-only)
-- because their UNIQUE constraints need to include it - two different
-- users legitimately CAN share a snapshot_date+account+symbol (e.g. the
-- same broker account-naming convention, or two people testing with the
-- same sample data), and the pre-multi-user constraints would otherwise
-- block the second user's import. transactions/value_log have no UNIQUE
-- constraint to widen, so they still just get user_id via the
-- ALTER-if-missing loop in portfolio.py's _ensure_schema, same as before.
-- Deployed databases that predate this (this app has exactly one: the
-- live one) needed a one-time explicit table-rebuild migration to widen
-- their already-existing constraints - CREATE TABLE IF NOT EXISTS alone
-- can't retrofit that onto a table that already exists.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,          -- hex pbkdf2_hmac('sha256', ...) digest
    password_salt TEXT    NOT NULL,          -- hex random salt (os.urandom(16))
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Advisor mode: which accounts each advisor manages. Who is an advisor is
-- users.is_advisor (added by portfolio.py's _ensure_schema), set only via
-- manage_users.py.
CREATE TABLE IF NOT EXISTS advisor_clients (
    advisor_id INTEGER NOT NULL,
    client_id  INTEGER NOT NULL,
    client_name TEXT,          -- what the advisor calls them ("Chen household"); auth.set_client_name
    PRIMARY KEY (advisor_id, client_id)
);

-- One row per (positions export file, as-of date) that has been imported.
CREATE TABLE IF NOT EXISTS snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT    NOT NULL,              -- ISO date parsed from the export header, e.g. 2026-08-28
    as_of_text    TEXT,                          -- raw "as of ..." string from the file
    source_file   TEXT    NOT NULL,              -- the CSV's path, 'upload: <name>', 'manual entry', 'percentages' or 'sample portfolio'
    user_id       INTEGER NOT NULL,
    imported_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (snapshot_date, source_file, user_id)
);

-- One row per real holding, per account, per snapshot.
-- Cash lines and "Positions Total" lines are NOT stored here.
CREATE TABLE IF NOT EXISTS positions (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date      TEXT    NOT NULL,
    account            TEXT    NOT NULL,          -- e.g. "Individual ...641"
    symbol             TEXT    NOT NULL,
    description        TEXT,
    asset_type         TEXT,                      -- Equity / ETFs & Closed End Funds / ...
    quantity           REAL,                      -- may be fractional (e.g. 252.7033)
    cost_basis         REAL,                      -- total cost basis for the lot, in dollars
    market_value       REAL,                      -- total market value, in dollars
    price_change_pct   REAL,
    day_change_pct     REAL,
    reported_gain      REAL,                      -- "Gain $" straight from the file (for reconciliation)
    reported_gain_pct  REAL,                      -- "Gain %" straight from the file
    reinvest           INTEGER,                   -- 1 = Yes, 0 = No, NULL = n/a
    reinvest_cap_gains INTEGER,
    div_pay_date       TEXT,
    div_yield_pct      REAL,
    next_earnings_date TEXT,
    pct_of_account     REAL,
    source_file        TEXT,
    user_id            INTEGER NOT NULL,
    imported_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (snapshot_date, account, symbol, user_id)
);

-- The skipped-but-useful rows: per account, the cash line's market value and the
-- "Positions Total" figures. Kept so the importer can prove the parsed holdings
-- reconcile to the totals the broker printed.
CREATE TABLE IF NOT EXISTS account_totals (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date         TEXT    NOT NULL,
    account               TEXT    NOT NULL,
    cash_value            REAL,                   -- "Cash & Cash Investments" market value
    reported_cost_basis   REAL,                   -- "Positions Total" cost basis (holdings only)
    reported_market_value REAL,                   -- "Positions Total" market value (holdings + cash)
    reported_gain         REAL,                   -- "Positions Total" gain $
    reported_gain_pct     REAL,                   -- "Positions Total" gain %
    source_file           TEXT,
    user_id               INTEGER NOT NULL,
    imported_at           TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE (snapshot_date, account, user_id)
);

-- Live quotes fetched by update_prices.py. Append-only: one row per ticker per run.
CREATE TABLE IF NOT EXISTS price_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker     TEXT    NOT NULL,
    price      REAL,                             -- current price ("c" from Finnhub); NULL if the fetch failed
    prev_close REAL,                             -- "pc"
    change     REAL,                             -- "d"
    pct_change REAL,                             -- "dp"
    day_open   REAL,                             -- "o"
    day_high   REAL,                             -- "h"
    day_low    REAL,                             -- "l"
    quote_time TEXT,                             -- exchange timestamp, ISO-8601 UTC ("t" from Finnhub)
    fetched_at TEXT    NOT NULL DEFAULT (datetime('now')),   -- when this row was written, ISO-8601 UTC
    source     TEXT    NOT NULL DEFAULT 'finnhub',
    ok         INTEGER NOT NULL DEFAULT 1,       -- 0 = fetch failed or no data for the symbol
    error      TEXT,
    raw        TEXT                              -- raw JSON body, for debugging
);
CREATE INDEX IF NOT EXISTS idx_price_history_ticker ON price_history (ticker, fetched_at);

-- Rows are *inferred* from the quantity delta between two imported snapshots
-- (the Positions export has no real trade history) - see changes.py.
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account       TEXT    NOT NULL,
    trade_date    TEXT,
    settle_date   TEXT,
    action        TEXT,                             -- BUY / SELL / DIV / REINVEST / ...
    symbol        TEXT,
    description   TEXT,
    quantity      REAL,
    price         REAL,
    amount        REAL,                             -- signed cash impact
    fees          REAL,
    realized_gain REAL,                              -- SELL only; average-cost method, NULL for BUY
    source_file   TEXT,
    origin        TEXT,                             -- 'imported' (txn_import.py); NULL = worked out from updates
    row_key       TEXT,                             -- an imported row's fingerprint, so re-imports add only what's new
    imported_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Portfolio-level aggregates over time. One row is appended per app session
-- open (see perf.py); historical CSV snapshots are folded in when charting.
CREATE TABLE IF NOT EXISTS value_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at           TEXT    NOT NULL,            -- ISO-8601 UTC, when this row was written
    snapshot_date       TEXT,                        -- the CSV snapshot in effect at the time
    source              TEXT    NOT NULL DEFAULT 'app_open',   -- app_open | snapshot | manual
    portfolio_value     REAL,
    holdings_value      REAL,
    cash                REAL,
    cost_basis          REAL,
    unrealized_gain     REAL,
    unrealized_gain_pct REAL,
    day_change_usd      REAL,                        -- sum of per-position day $ change
    n_positions         INTEGER,
    n_priced            INTEGER,                     -- how many had live prices
    priced_at           TEXT                         -- max(live_price_at) at the time
);
CREATE INDEX IF NOT EXISTS idx_value_log_time ON value_log (logged_at);

-- Real daily OHLCV history, fetched from Yahoo via sync_history.py (yfinance).
-- One row per (ticker, trading day). Upserted, so a re-sync refreshes.
CREATE TABLE IF NOT EXISTS daily_bars (
    ticker     TEXT    NOT NULL,
    date       TEXT    NOT NULL,                    -- trading day, YYYY-MM-DD
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    adj_close  REAL,
    volume     INTEGER,
    source     TEXT    NOT NULL DEFAULT 'yfinance',
    fetched_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, date)
);
-- (the primary key already indexes (ticker, date); an old copy is dropped in portfolio._ensure_schema)

-- Intraday OHLCV, several resolutions, fetched from Yahoo via sync_history.py.
-- Yahoo only keeps a limited look-back per resolution (roughly: 1m ~ 8 days,
-- 5m/15m ~ 60 days, 60m ~ 2 years) - sync_history.py requests the maximum each
-- allows. One row per (ticker, interval, bar timestamp). Upserted.
CREATE TABLE IF NOT EXISTS intraday_bars (
    ticker     TEXT    NOT NULL,
    interval   TEXT    NOT NULL,                    -- '1m' | '5m' | '15m' | '60m'
    ts         TEXT    NOT NULL,                    -- bar start, ISO-8601 UTC
    open       REAL,
    high       REAL,
    low        REAL,
    close      REAL,
    volume     INTEGER,
    source     TEXT    NOT NULL DEFAULT 'yfinance',
    fetched_at TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (ticker, interval, ts)
);
-- (the primary key already indexes (ticker, interval, ts))

-- Point-in-time fundamentals / reference data, fetched alongside the bars.
-- One row per ticker, replaced on each sync.
CREATE TABLE IF NOT EXISTS security_info (
    ticker         TEXT    PRIMARY KEY,
    name           TEXT,
    sector         TEXT,
    industry       TEXT,
    market_cap     REAL,
    beta           REAL,
    trailing_pe    REAL,
    forward_pe     REAL,
    price_to_book  REAL,
    dividend_yield REAL,                            -- as returned by Yahoo (may be % or fraction)
    week52_high    REAL,
    week52_low     REAL,
    avg_volume     INTEGER,
    avg_volume_10d INTEGER,
    source         TEXT    NOT NULL DEFAULT 'yfinance',
    fetched_at     TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- A fund's top holdings from Yahoo (fund_holdings.py, the Fund overlap window):
-- shared market data like security_info, no user_id. Fetched on demand and
-- asked again at most once a week. Slot 0 records when the fund was asked
-- (no holding: Yahoo may list none); slots 1.. are its largest holdings.
CREATE TABLE IF NOT EXISTS fund_top_holdings (
    fund        TEXT    NOT NULL,                   -- the fund's ticker, as held
    slot        INTEGER NOT NULL,                   -- 1 = its largest; 0 = when it was asked
    symbol      TEXT,                               -- the holding's ticker ('' if none)
    name        TEXT,
    weight      REAL,                               -- a fraction of the fund (0.064 = 6.4%)
    source      TEXT    NOT NULL DEFAULT 'yfinance',
    fetched_at  TEXT    NOT NULL,                   -- ISO 'YYYY-MM-DDTHH:MM:SSZ' UTC
    PRIMARY KEY (fund, slot)
);

-- AI Assistant investing profile, one row per account (see advisor.py).
-- updated_at is always written explicitly, never left to a DEFAULT.
CREATE TABLE IF NOT EXISTS investor_profiles (
    user_id            INTEGER PRIMARY KEY,
    goal               TEXT,
    time_horizon_years INTEGER,
    target_return_pct  REAL,
    risk_tolerance     TEXT,                      -- conservative | moderate | aggressive
    experience         TEXT,                      -- new | some | experienced
    drawdown_reaction  TEXT,
    age_range          TEXT,
    income_stability   TEXT,
    emergency_fund     TEXT,
    high_interest_debt TEXT,
    employer_match     TEXT,
    contributions      TEXT,
    withdrawal_needs   TEXT,
    preferences        TEXT,
    ai_memory          TEXT,                      -- the assistant's own notes, never shown in the app
    notes              TEXT,
    updated_at         TEXT
);

-- Tickers tracked for their chart/stats without being an owned position.
-- Per-user: two different accounts can each watch the same ticker.
CREATE TABLE IF NOT EXISTS watchlist (
    user_id    INTEGER NOT NULL,
    ticker     TEXT    NOT NULL,
    added_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, ticker)
);

-- Company news headlines from Finnhub's /company-news endpoint, cached per
-- ticker so opening a ticker's detail view doesn't re-fetch on every page
-- load. `id` is Finnhub's own article id - a natural key for INSERT OR
-- IGNORE dedup across repeated syncs.
CREATE TABLE IF NOT EXISTS news (
    id           INTEGER PRIMARY KEY,
    ticker       TEXT    NOT NULL,
    headline     TEXT,
    summary      TEXT,
    source       TEXT,
    url          TEXT,
    published_at TEXT,                              -- ISO-8601 UTC, from Finnhub's epoch
    fetched_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_news_ticker ON news (ticker, published_at);

-- A user's own display name for a broker account ("Roth IRA" instead of
-- "Individual ...111"). Display only: positions keep the broker's name.
CREATE TABLE IF NOT EXISTS account_labels (
    user_id    INTEGER NOT NULL,
    account    TEXT    NOT NULL,
    nickname   TEXT    NOT NULL,
    PRIMARY KEY (user_id, account)
);

-- "Stay signed in": one row per signed-in browser. Only a SHA-256 hash of
-- the cookie's random token is stored, so a copy of this table can't be used
-- to sign in. Rows are deleted on logout and on a password change.
-- two_step_until: "remember this device" (two_step.remember_device) - until
-- then this browser isn't asked for a two-step code (NULL: it is).
CREATE TABLE IF NOT EXISTS login_sessions (
    token_hash  TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    expires_at  TEXT    NOT NULL,                    -- 'YYYY-MM-DD HH:MM:SS' UTC
    two_step_until TEXT                              -- 'YYYY-MM-DD HH:MM:SS' UTC
);

-- Two-step sign-in (two_step.py, ROADMAP R2): one row per login that has it
-- on. The authenticator app's secret key has to be readable to check codes,
-- so it is never shown again after setup, never exported and never shown to
-- an admin. Backup codes are kept only as SHA-256 hashes (space-separated,
-- unused ones only). last_token_step stops one code being used twice.
CREATE TABLE IF NOT EXISTS two_step (
    user_id           INTEGER PRIMARY KEY,
    totp_secret       TEXT    NOT NULL,              -- base32
    backup_codes_hash TEXT    NOT NULL DEFAULT '',
    enabled_at        TEXT    NOT NULL,              -- 'YYYY-MM-DD HH:MM:SS' UTC
    last_token_step   INTEGER NOT NULL DEFAULT 0
);

-- One-time setup links an advisor sends a client (auth.create_invite): the
-- client opens it and chooses their own password, so none is ever shared.
-- Only the token's hash is kept; a link works once, until expires_at.
CREATE TABLE IF NOT EXISTS invites (
    token_hash  TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL,                    -- the client account it sets up
    created_by  INTEGER NOT NULL,                    -- the advisor
    created_at  TEXT    NOT NULL,                    -- 'YYYY-MM-DD HH:MM:SS' UTC
    expires_at  TEXT    NOT NULL
);

-- How many AI requests each account made per month, per feature, and what
-- they cost (ai_usage.py enforces the daily and monthly allowances in cost).
-- Counts and costs only - never what was asked.
CREATE TABLE IF NOT EXISTS ai_usage (
    user_id  INTEGER NOT NULL,
    month    TEXT    NOT NULL,                       -- 'YYYY-MM' (UTC)
    kind     TEXT    NOT NULL,                       -- chat / screenshot / csv / plan / prep
    used     INTEGER NOT NULL,
    cost_micro     INTEGER NOT NULL DEFAULT 0,       -- this month, micro-dollars
    day            TEXT,                             -- 'YYYY-MM-DD' (UTC) last used
    day_cost_micro INTEGER NOT NULL DEFAULT 0,       -- on that day, micro-dollars
    PRIMARY KEY (user_id, month, kind)
);

-- Per-account dashboard settings (chosen columns, alert limits, hide
-- amounts, ...) as one JSON object. Was a .dashboard_prefs.<id>.json file,
-- which a hosted app loses on every restart.
CREATE TABLE IF NOT EXISTS user_prefs (
    user_id   INTEGER PRIMARY KEY,
    data      TEXT    NOT NULL
);

-- One plan per account: a goal, how much is added toward it, and a target
-- mix. Written by the account owner or their advisor (set_by).
CREATE TABLE IF NOT EXISTS plans (
    user_id              INTEGER PRIMARY KEY,
    goal_type            TEXT,
    goal_name            TEXT,
    target_amount        REAL,
    target_date          TEXT,                  -- YYYY-MM-DD
    monthly_contribution REAL,
    target_alloc         TEXT,                  -- JSON {asset class: target %} (asset_classes.py)
    notes                TEXT,
    set_by               INTEGER,               -- users.id of whoever last saved it
    updated_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Money added to (or, negative, taken out of) an account, logged by hand.
CREATE TABLE IF NOT EXISTS contributions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    date        TEXT    NOT NULL,               -- YYYY-MM-DD
    amount      REAL    NOT NULL,
    note        TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_contributions_user ON contributions (user_id, date);

-- Money going out of a plan (plans.py, ROADMAP 12): planned expenses (an
-- amount on a date, `times` times every `every_months`) and at most one
-- regular withdrawal (a monthly amount from start_date to end_date, if set,
-- rising inflation_pct a year if set). Saved by the owner or their advisor.
CREATE TABLE IF NOT EXISTS money_out (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER NOT NULL,
    kind          TEXT    NOT NULL,               -- 'expense' | 'withdrawal'
    label         TEXT,
    amount        REAL NOT NULL,
    start_date    TEXT    NOT NULL,               -- YYYY-MM-DD
    end_date      TEXT,                           -- a withdrawal's last month, if any
    times         INTEGER NOT NULL DEFAULT 1,
    every_months  INTEGER NOT NULL DEFAULT 12,
    inflation_pct REAL,                    -- NULL: the same amount every year
    set_by        INTEGER,                        -- users.id of whoever last saved it
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Advisor notes on a client's account (advising.py): a Review (meeting), a
-- Note, or a Next step (done when the advisor ticks it). Private notes are
-- never shown to the client. Nothing is deleted from the app: Archive hides a
-- note (archived_at) and an edit keeps the earlier text (history), so the
-- advisor keeps a record they can export (export.client_record_zip).
CREATE TABLE IF NOT EXISTS advisor_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    client_id   INTEGER NOT NULL,
    advisor_id  INTEGER NOT NULL,
    kind        TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    note_date   TEXT    NOT NULL,                -- YYYY-MM-DD
    private     INTEGER NOT NULL DEFAULT 0,
    done        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    archived_at TEXT,                            -- 'YYYY-MM-DD HH:MM:SS' UTC; NULL = showing
    edited_at   TEXT,                            -- the last edit, UTC
    history     TEXT,                            -- JSON list of earlier versions (advising.edit_note)
    is_message  INTEGER                          -- 1: sent with Message clients
);
CREATE INDEX IF NOT EXISTS idx_advisor_notes_client ON advisor_notes (client_id, note_date);

-- An advisor's saved target mixes by asset type, applied to clients' plans.
CREATE TABLE IF NOT EXISTS model_portfolios (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    advisor_id    INTEGER NOT NULL,
    name          TEXT    NOT NULL,
    target_alloc  TEXT    NOT NULL,              -- JSON {asset class: target %} (asset_classes.py)
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Failed logins per username, for the lockout (auth.attempt_login): after
-- MAX_FAILED_LOGINS wrong passwords in LOCKOUT_MINUTES, that username is
-- locked for LOCKOUT_MINUTES. Keyed by a SHA-256 of the username as typed
-- (case-folded), known or not - so the lock reveals nothing about which
-- usernames exist, and a password typed into the username box isn't stored.
CREATE TABLE IF NOT EXISTS login_failures (
    username_key  TEXT    PRIMARY KEY,
    failures      INTEGER NOT NULL,
    window_start  TEXT    NOT NULL,              -- 'YYYY-MM-DD HH:MM:SS' UTC
    locked_until  TEXT
);

-- Sign-up tries, for the limits on new accounts (auth.sign_up). Keyed by a
-- SHA-256 of the internet address ('' if unknown) - never the address or the
-- email - and kept for a day. The no-account decoder's hourly limit counts
-- here too, keyed 'decoder:' + that hash (decoder_public.py).
CREATE TABLE IF NOT EXISTS signups (
    address_key  TEXT    NOT NULL,
    created_at   TEXT    NOT NULL,               -- 'YYYY-MM-DD HH:MM:SS' UTC
    ok           INTEGER NOT NULL                -- 1 = an account was made
);

-- One-time links emailed to people (auth.start_confirmation /
-- request_password_reset): confirm an email, or reset a password. Only the
-- token's hash is stored; `email` is the address it was sent to, so a link
-- stops working if the account's email changes.
CREATE TABLE IF NOT EXISTS email_tokens (
    token_hash  TEXT    PRIMARY KEY,
    user_id     INTEGER NOT NULL,
    purpose     TEXT    NOT NULL,                -- 'confirm', 'reset' or 'change' (email = the new one); 'confirmed' = a used confirm link, kept a day; 'unsub_walk' / 'unsub_weekly' / 'unsub_trail' = an email's unsubscribe link (unsubscribe.py, a year)
    email       TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,                -- 'YYYY-MM-DD HH:MM:SS' UTC
    expires_at  TEXT    NOT NULL
);

-- An advisor's proposed mix for a client (proposals.py): a draft only the
-- advisor sees, then shared, then the client's answer. Only a draft can be
-- deleted; once shared it's part of the advisor's record: Archive hides it
-- (archived_at) and keeps it, like advisor notes (proposals.archive).
CREATE TABLE IF NOT EXISTS proposals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    advisor_id    INTEGER NOT NULL,
    client_id     INTEGER NOT NULL,
    title         TEXT    NOT NULL,
    mix_json      TEXT    NOT NULL,              -- JSON {asset class: %} (asset_classes.py)
    note          TEXT,                          -- the advisor's reasoning, for the client
    status        TEXT    NOT NULL,              -- draft / shared / accepted / declined
    created_at    TEXT    NOT NULL,
    updated_at    TEXT    NOT NULL,
    shared_at     TEXT,
    responded_at  TEXT,
    archived_at   TEXT                           -- 'YYYY-MM-DD HH:MM:SS' UTC; shared ones are archived, never deleted
);

-- Progress reports an advisor sends a client (reports.py): the figures as
-- they were when sent, and the advisor's message.
CREATE TABLE IF NOT EXISTS progress_reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    advisor_id    INTEGER NOT NULL,
    client_id     INTEGER NOT NULL,
    period_label  TEXT    NOT NULL,              -- e.g. "Q3 2026"
    period_start  TEXT    NOT NULL,              -- YYYY-MM-DD
    period_end    TEXT    NOT NULL,
    facts_json    TEXT    NOT NULL,              -- reports.build()
    message       TEXT,
    created_at    TEXT    NOT NULL,
    read_at       TEXT
);

-- Asking for advisor access (auth.request_advisor): the firm and CRD or
-- licence number the admin checks before making the account an advisor
-- (manage_users.py make-advisor / decline-advisor). One row per account.
CREATE TABLE IF NOT EXISTS advisor_requests (
    user_id       INTEGER PRIMARY KEY,
    firm          TEXT    NOT NULL,
    licence       TEXT    NOT NULL,
    requested_at  TEXT    NOT NULL,              -- 'YYYY-MM-DD HH:MM:SS' UTC
    decision      TEXT,                          -- NULL while waiting, 'approved', 'declined'
    decided_at    TEXT
);

-- An advisor's directory listing (directory.py; PLAN step 5, flag `directory`,
-- gate L2): what they show on Find a guide, as they entered it. One row per
-- advisor. The lists (credentials, fee_models, serves, states) are JSON text
-- of the keys in directory.py. Shown only when listed = 1, the profile is
-- complete and the account is an approved advisor (directory.visible). No
-- order, rank or count of any kind: listings are alphabetical by name, and
-- nothing about who browses is kept (brief 3.4).
CREATE TABLE IF NOT EXISTS advisor_profiles (
    user_id        INTEGER PRIMARY KEY,          -- the advisor
    display_name   TEXT    NOT NULL DEFAULT '',
    firm           TEXT    NOT NULL DEFAULT '',
    reg_type       TEXT    NOT NULL DEFAULT '',  -- directory.REG_TYPES
    reg_number     TEXT    NOT NULL DEFAULT '',  -- their CRD number, as entered
    credentials    TEXT    NOT NULL DEFAULT '[]',
    fee_models     TEXT    NOT NULL DEFAULT '[]',
    minimum        TEXT    NOT NULL DEFAULT '',  -- directory.MINIMUMS (a band)
    serves         TEXT    NOT NULL DEFAULT '[]',
    states         TEXT    NOT NULL DEFAULT '[]',
    meeting        TEXT    NOT NULL DEFAULT '',  -- 'virtual' | 'in_person' | 'both'
    description    TEXT    NOT NULL DEFAULT '',
    scheduling_url TEXT    NOT NULL DEFAULT '',  -- https only
    one_time_cost  TEXT    NOT NULL DEFAULT '',  -- '' not offered, 'ask', or whole dollars (ADR 0005)
    listed         INTEGER NOT NULL DEFAULT 0,   -- the advisor's own switch
    updated_at     TEXT    NOT NULL              -- ISO 'YYYY-MM-DDTHH:MM:SSZ' UTC
);

-- A relationship an advisor or their client ended (advising.end_relationship).
-- The client keeps their account; the advisor keeps their own notes,
-- proposals and reports about them (export.client_record), and this row says
-- who they were to the advisor: the advisor's name for them and their email
-- when it ended. One row per advisor and former client.
CREATE TABLE IF NOT EXISTS former_clients (
    advisor_id   INTEGER NOT NULL,
    client_id    INTEGER NOT NULL,
    client_name  TEXT,                           -- the advisor's name for them then
    email        TEXT,                           -- their email then, if any
    ended_at     TEXT    NOT NULL,               -- 'YYYY-MM-DD HH:MM:SS' UTC
    ended_by     TEXT    NOT NULL,               -- 'advisor' or 'client'
    account      TEXT    NOT NULL,               -- 'kept', 'setup link' or 'closed'
    PRIMARY KEY (advisor_id, client_id)
);

-- Emails asked for, for the limits on them (auth._email_limit). Hashes of the
-- email typed and the internet address only; kept for a day. The same day-long
-- counts serve the other per-account limits: advisors' client checks
-- ('client_check') and how often a login uploads, saves and builds downloads
-- (rate_limits.py: 'limit_upload' / 'limit_save' / 'limit_export', keyed by a
-- hash of the login's id) - counts only, never what was done.
CREATE TABLE IF NOT EXISTS email_sends (
    email_key    TEXT NOT NULL,
    address_key  TEXT NOT NULL,                  -- '' if unknown
    purpose      TEXT NOT NULL,
    sent_at      TEXT NOT NULL                   -- 'YYYY-MM-DD HH:MM:SS' UTC
);

-- Column layouts of brokerage CSVs seen before (csv_import.py): a fingerprint
-- of the column NAMES -> which column holds which field. No holdings or
-- personal data - so the next file with the same columns needs no questions.
CREATE TABLE IF NOT EXISTS csv_layouts (
    signature   TEXT PRIMARY KEY,
    mapping     TEXT NOT NULL,                   -- JSON {field: column index}
    updated_at  TEXT NOT NULL
);

-- Account map (account_map.py, ROADMAP 10): the person's own "if something
-- happens to me" binder. entry 'account': what they filled in for an account
-- they brought in (`account` its saved name, already cut to the last 3
-- digits); 'other': one they added by hand (label, last_digits - 3 at most);
-- 'family': their notes for family (notes), one per person. Private: never
-- shown to an advisor, never emailed, never sent to the AI.
CREATE TABLE IF NOT EXISTS account_map (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    entry        TEXT    NOT NULL,               -- 'account' | 'other' | 'family'
    account      TEXT,
    label        TEXT,
    last_digits  TEXT,
    kind         TEXT,                           -- account_map.KINDS
    contact      TEXT,                           -- who to call
    phone        TEXT,
    beneficiary  TEXT,                           -- 'Yes' | 'No' | 'Not sure'
    paperwork    TEXT,                           -- where the paperwork is
    notes        TEXT,
    updated_at   TEXT    NOT NULL                -- ISO 'YYYY-MM-DDTHH:MM:SSZ' UTC
);

-- Unexpected errors and failed scheduled jobs, one row per kind (error_alerts.py):
-- the error's type and the file/function where it happened - never its message,
-- anyone's data or a user_id. Limits the admin's alert emails to one an hour.
CREATE TABLE IF NOT EXISTS error_events (
    kind        TEXT PRIMARY KEY,                -- 'KeyError in views/plan.py, _render_tab'
    source      TEXT    NOT NULL,                -- 'app' or 'job'
    error_type  TEXT    NOT NULL,
    place       TEXT    NOT NULL,                -- 'views/plan.py, _render_tab' or the job
    line        INTEGER,                         -- line of the latest one
    first_seen  TEXT    NOT NULL,                -- ISO 'YYYY-MM-DDTHH:MM:SSZ' UTC
    last_seen   TEXT    NOT NULL,
    times       INTEGER NOT NULL DEFAULT 1,
    emailed_at  TEXT                             -- last alert email, NULL if none
);

-- The app-wide AI spend (ai_spend.py): token counts and an estimated cost per
-- month, helper and model. Counts only - no user_id, no question or answer text.
CREATE TABLE IF NOT EXISTS ai_spend (
    month              TEXT    NOT NULL,         -- 'YYYY-MM' (UTC)
    helper             TEXT    NOT NULL,         -- 'chat', 'prep', 'screenshot', 'csv', 'txn'; 'check:<kind>' counts the output check's breaks (no tokens, no cost)
    model              TEXT    NOT NULL,
    calls              INTEGER NOT NULL DEFAULT 0,
    input_tokens       INTEGER NOT NULL DEFAULT 0,
    output_tokens      INTEGER NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER NOT NULL DEFAULT 0,
    cost_micro         INTEGER NOT NULL DEFAULT 0,  -- estimated, micro-dollars
    updated_at         TEXT    NOT NULL,         -- ISO 'YYYY-MM-DDTHH:MM:SSZ' UTC
    PRIMARY KEY (month, helper, model)
);

-- Which spend alerts (50%, 80% of the ceiling) the admin was sent this month.
CREATE TABLE IF NOT EXISTS ai_alerts (
    month    TEXT    NOT NULL,                   -- 'YYYY-MM'
    level    INTEGER NOT NULL,                   -- the percent: 50 or 80
    sent_at  TEXT    NOT NULL,
    PRIMARY KEY (month, level)
);

-- Notes to future you (future_notes.py): a note a person writes to themselves on
-- a holding (symbol) or on their plan (symbol NULL). Private: never shown to an
-- advisor or sent to the AI unless they ask it about the note.
CREATE TABLE IF NOT EXISTS future_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    symbol      TEXT,                            -- NULL: the plan's note
    body        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,                -- ISO 'YYYY-MM-DDTHH:MM:SSZ' UTC
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_future_notes_user ON future_notes (user_id, symbol);

-- Invite codes (invite_codes.py): while gate L0 is off, Create account needs one.
-- Made by an admin, each works once. Kept as typed (single-use, low value; the
-- admin hands unused ones out again). Deleting an account clears created_by /
-- used_by (admin.ACCOUNT_REFERENCES); a used code stays used.
CREATE TABLE IF NOT EXISTS invite_codes (
    code        TEXT    PRIMARY KEY,             -- 8 characters, no look-alikes
    note        TEXT,                            -- the admin's note: who it's for
    created_by  INTEGER,                         -- the admin who made it
    created_at  TEXT    NOT NULL,                -- 'YYYY-MM-DD HH:MM:SS' UTC
    used_at     TEXT,                            -- NULL until it's used
    used_by     INTEGER,                         -- the account it made
    revoked_at  TEXT                             -- NULL unless the admin stopped it
);

CREATE INDEX IF NOT EXISTS idx_positions_snapshot   ON positions (snapshot_date);
CREATE INDEX IF NOT EXISTS idx_positions_symbol     ON positions (symbol);
CREATE INDEX IF NOT EXISTS idx_transactions_symbol  ON transactions (symbol);
CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions (account);

-- App-wide numbers (auth.py). 'session_gen' goes up by one each time the admin
-- signs everyone out (auth.sign_out_everyone; Admin > System or manage_users.py
-- sign-out-all); every open tab compares it on each run, with its login's own
-- users.session_gen, and lands on sign-in when either has moved (audit X5).
CREATE TABLE IF NOT EXISTS app_state (
    name    TEXT    PRIMARY KEY,
    number  INTEGER NOT NULL DEFAULT 0
);

-- The admin action log (admin_log.py; PLAN 1b.3, audit X2): who did what to
-- which login, and when. Append-only - only admin_log.prune removes rows (after
-- a year). Never holdings or figures. Deleting an account clears admin_id /
-- target_id (admin.ACCOUNT_REFERENCES); the row stays.
CREATE TABLE IF NOT EXISTS admin_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT    NOT NULL,                -- 'YYYY-MM-DD HH:MM:SS' UTC
    admin_id    INTEGER,                         -- the admin's login; NULL: the command line
    action      TEXT    NOT NULL,                -- one of admin_log.ACTIONS
    target_id   INTEGER,                         -- the account it was done to, if any
    detail      TEXT                             -- a few words made by the code
);
CREATE INDEX IF NOT EXISTS idx_admin_log_at ON admin_log (at);

-- The advisor agreement (advisor_agreement.py; master brief 4.1, gate L1): each
-- time an advisor accepts a version - which version, a SHA-256 of the exact text
-- they were shown, whether gate L1 was on then (off: shown marked "Beta") and
-- when. A new row for every acceptance; the latest one counts. Deleted with the
-- account (admin.ACCOUNT_TABLES); in their own export (export.OWN).
CREATE TABLE IF NOT EXISTS advisor_agreements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,                -- the advisor
    version      TEXT    NOT NULL,                -- advisor_agreement.VERSION
    text_hash    TEXT    NOT NULL,                -- SHA-256 of the text shown
    l1_on        INTEGER NOT NULL DEFAULT 0,      -- 1: gate L1 was on (not the beta text)
    accepted_at  TEXT    NOT NULL                 -- 'YYYY-MM-DD HH:MM:SS' UTC
);
CREATE INDEX IF NOT EXISTS idx_advisor_agreements_user ON advisor_agreements (user_id, id);

-- Licence checks (licence_check.py; PLAN D15): each time the admin looked an
-- advisor up - at approval and about once a year after - where (BrokerCheck or
-- IAPD), the CRD or licence number that matched, and the day. A new row each
-- time; the latest one counts (due after 11 months, not current after 13).
-- Deleted with the advisor's account; checked_by (the admin) is cleared when
-- that admin's account is deleted (admin.ACCOUNT_REFERENCES).
CREATE TABLE IF NOT EXISTS licence_checks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    advisor_id   INTEGER NOT NULL,
    source       TEXT    NOT NULL,                -- 'BrokerCheck' or 'IAPD'
    crd          TEXT    NOT NULL,                -- the CRD or licence number matched
    checked_on   TEXT    NOT NULL,                -- 'YYYY-MM-DD', the day it was looked up
    checked_by   INTEGER,                         -- the admin; NULL: the command line
    recorded_at  TEXT    NOT NULL                 -- 'YYYY-MM-DD HH:MM:SS' UTC
);
CREATE INDEX IF NOT EXISTS idx_licence_checks_advisor ON licence_checks (advisor_id, checked_on);

-- Consent records (consent.py; PLAN step 5.6, audit 1.6f): a client's grant
-- or revoke of sharing with an advisor, with the exact words shown (verbatim,
-- and their SHA-256). Append-only - only consent.prune removes rows, 7 years
-- after the sharing ended (PLAN B6). Kept when either account is deleted
-- (admin.KEPT_AFTER_DELETE): ids, times and words, never figures.
CREATE TABLE IF NOT EXISTS consent_records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT    NOT NULL,                -- 'YYYY-MM-DDTHH:MM:SSZ' UTC
    client_id   INTEGER NOT NULL,
    advisor_id  INTEGER NOT NULL,
    kind        TEXT    NOT NULL,                -- 'grant' | 'revoke'
    scope       TEXT    NOT NULL,                -- 'full_sharing' | 'advisor_pack' | 'walk_signal' | 'together' (consent.SCOPES)
    text_shown  TEXT,                            -- verbatim; a revoke may have none
    text_sha256 TEXT,
    how         TEXT    NOT NULL                 -- consent.HOWS: 'setup_link', 'client_stop'...
);
CREATE INDEX IF NOT EXISTS idx_consent_records_pair ON consent_records (client_id, advisor_id);

-- The advisor access log (access_log.py; PLAN step 5.8, audit 1.6f): one row
-- per page an advisor opens in a client's account. Never figures. Append-only
-- - only access_log.prune removes rows, after 7 years (PLAN B6). Kept when
-- either account is deleted (admin.KEPT_AFTER_DELETE).
CREATE TABLE IF NOT EXISTS advisor_access_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT    NOT NULL,                -- 'YYYY-MM-DDTHH:MM:SSZ' UTC
    advisor_id  INTEGER NOT NULL,
    client_id   INTEGER NOT NULL,
    page        TEXT    NOT NULL                 -- the app's page name ('Dashboard', 'Plan'...)
);
CREATE INDEX IF NOT EXISTS idx_advisor_access_log_client ON advisor_access_log (client_id, at);
CREATE INDEX IF NOT EXISTS idx_advisor_access_log_at ON advisor_access_log (at);

-- Introductions (intros.py; PLAN step 5.5-5.6): a person who found an advisor
-- in Find a guide asked to be introduced. One row per introduction actually
-- sent - nothing about browsing is ever written. The advisor sees only the
-- name the person gave, their message and the figure-free outline they chose
-- to send (outline: JSON - asset-class mix in whole percents, goals, a
-- timeline bucket, the route stage; never amounts, share counts, tickers or
-- account details). Deleted with either account (admin.ACCOUNT_TABLES).
CREATE TABLE IF NOT EXISTS intro_requests (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id    INTEGER NOT NULL,                -- who asked
    advisor_id   INTEGER NOT NULL,                -- the advisor they wrote to
    created_at   TEXT    NOT NULL,                -- 'YYYY-MM-DDTHH:MM:SSZ' UTC
    person_name  TEXT    NOT NULL,                -- the name they gave the advisor
    message      TEXT    NOT NULL DEFAULT '',     -- plain text, intros.LIMITS
    outline      TEXT    NOT NULL DEFAULT '{}',   -- what they chose to send (intros.clean_outline)
    status       TEXT    NOT NULL DEFAULT 'sent', -- intros.STATUSES: sent | replied | declined | withdrawn | shared
    reply        TEXT,                            -- the advisor's answer, plain text
    replied_at   TEXT,
    link_shared  INTEGER NOT NULL DEFAULT 0,      -- the advisor shared their scheduling link
    closed_at    TEXT                             -- declined, withdrawn or shared
);
CREATE INDEX IF NOT EXISTS idx_intro_requests_person ON intro_requests (person_id, created_at);
CREATE INDEX IF NOT EXISTS idx_intro_requests_advisor ON intro_requests (advisor_id, status);

-- Share links (explain_share.py, ROADMAP R10 "Explain it to someone"): a
-- private link the account's owner makes to show a partner or family member
-- their plan in plain words - percentages and words only, never a figure,
-- holding or account detail, drawn from current data when it's opened. Only
-- the token's SHA-256 is kept (the link is shown once); it works until
-- expires_at, and turning it off deletes the row. opens / last_opened_on
-- ('YYYY-MM-DD') are for the owner only - nothing about who opened it.
-- Deleted with the account (admin.ACCOUNT_TABLES); ended ones by tidy.py.
CREATE TABLE IF NOT EXISTS share_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL,               -- the owner, who made it
    token_hash      TEXT    NOT NULL UNIQUE,        -- SHA-256 of the token, never the token
    created_at      TEXT    NOT NULL,               -- 'YYYY-MM-DDTHH:MM:SSZ' UTC
    expires_at      TEXT    NOT NULL,               -- 'YYYY-MM-DDTHH:MM:SSZ' UTC
    show_name       INTEGER NOT NULL DEFAULT 0,     -- 1 = the page shows their first name
    opens           INTEGER NOT NULL DEFAULT 0,     -- how many visits (owner only)
    last_opened_on  TEXT                            -- 'YYYY-MM-DD' of the last visit
);
CREATE INDEX IF NOT EXISTS idx_share_links_user ON share_links (user_id, expires_at);
-- "Price look wrong?" on a ticker's details (price_report.py, flag
-- price_report): one row per note a person sent - a fixed reason, never free
-- text. Kept with their account until it's deleted (admin.ACCOUNT_TABLES) and
-- in their own export; admins see counts by ticker and reason only.
CREATE TABLE IF NOT EXISTS price_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,                -- the login that sent it
    ticker       TEXT    NOT NULL,
    reason       TEXT    NOT NULL,                -- a price_report.REASONS key
    shown_price  REAL,                            -- the price on the page then
    price_as_of  TEXT,                            -- that price's time, 'YYYY-MM-DDTHH:MM:SSZ' UTC
    created_at   TEXT    NOT NULL                 -- 'YYYY-MM-DDTHH:MM:SSZ' UTC
);
CREATE INDEX IF NOT EXISTS idx_price_reports_user ON price_reports (user_id, created_at);
-- Bring to my advisor (advisor_pack.py, flag advisor_pack): one row per item a
-- client chose to show their advisor - a fixed key (a kind, a Trail Fork's
-- key or a question's key), never free text, and the day they ticked it.
-- Unticking deletes the row at once; the relationship ending deletes them all
-- (advisor_pack.on_unlink). Deleted with either account (admin.ACCOUNT_TABLES);
-- in the client's own export. The consent to it is in consent_records.
CREATE TABLE IF NOT EXISTS advisor_pack (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,                -- the client, who chose it
    advisor_id  INTEGER NOT NULL,                -- the advisor it's shown to
    item        TEXT    NOT NULL,                -- 'one_pager', 'fork:new_job', 'q:fees'...
    shared_on   TEXT    NOT NULL,                -- 'YYYY-MM-DD'
    UNIQUE (user_id, advisor_id, item)
);
-- Doing it together (together.py, flag together): two individuals' accounts
-- paired up, each seeing three habit facts about the other (learning days
-- this month, this month's walk done or not, wins earned) - never a figure.
-- together_invites: an invitation not yet answered - only the one-time
-- link's SHA-256 is kept (shown once), working until expires_at; deleted
-- when it's used or cancelled, ended ones by tidy.py.
-- together_pairs: one row per direction - user_id sees partner_id's three
-- facts; since, and when user_id last sent partner_id a nudge (once a
-- week). Stopping deletes both rows. Both deleted with either account
-- (admin.ACCOUNT_TABLES); the consent to it is in consent_records.
CREATE TABLE IF NOT EXISTS together_invites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,                -- who made the link
    token_hash  TEXT    NOT NULL UNIQUE,         -- SHA-256 of the token, never the token
    created_at  TEXT    NOT NULL,                -- 'YYYY-MM-DDTHH:MM:SSZ' UTC
    expires_at  TEXT    NOT NULL                 -- 'YYYY-MM-DDTHH:MM:SSZ' UTC
);
CREATE INDEX IF NOT EXISTS idx_together_invites_user ON together_invites (user_id, expires_at);
CREATE TABLE IF NOT EXISTS together_pairs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,                -- the one who sees
    partner_id  INTEGER NOT NULL,                -- the one whose three facts they see
    since       TEXT    NOT NULL,                -- 'YYYY-MM-DDTHH:MM:SSZ' UTC
    nudged_at   TEXT,                            -- when user_id last nudged partner_id
    UNIQUE (user_id, partner_id)
);
CREATE INDEX IF NOT EXISTS idx_together_pairs_partner ON together_pairs (partner_id);
