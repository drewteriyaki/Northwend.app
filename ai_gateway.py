"""The AI gateway (docs/AI_PLAN.md section 4, steps 4-5): every call to the
model goes through call(). No other module calls the API
(tests/test_legal_guardrails.py pins it).

For each call it:
1. looks the helper up in HELPERS - its model, answer length, effort, which
   allowance it uses and whether it could carry a dollar figure;
2. refuses a helper that could carry a dollar figure (carries_dollars) on a
   hosted copy until zero data retention is confirmed (settings.ai_zdr) -
   none of today's helpers is marked (see HELPERS);
3. checks the person's allowance (ai_usage.status, in cost, per day and
   month) and the month's app-wide level (ai_spend.level) - an advisor in a
   client's account uses their own allowance; a "system" helper (no person)
   is held to SYSTEM_BUDGET_MICRO a month instead;
4. builds the request (build_request: for the chat, the tools, then one
   cached block the same for everyone - the rules and Northwend's own guide -
   then the person's ContextCard, cached for the conversation, then the
   messages) and makes the call, streaming when asked;
5. records the answer's token counts and cost (ai_spend.note, and the
   person's own allowance with ai_usage.add_cost).

Nothing else is written or logged: never a prompt, an answer or an error's
text - this module has no print or logging at all. A refusal is a Refused
error carrying one calm sentence for the page (ai_usage.failure_text).

The write rule (AI_PLAN section 6, step 12): no model output reaches the
database on its own. The chat's profile tool only suggests (the person taps
to save); its notes are typed and scrubbed (advisor.MemoryNote) and saved by
save_memory() below, on the person's behalf, and only in their own account.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import anthropic

import ai_spend
import ai_usage
import settings

SONNET = "claude-sonnet-5"                 # advisor.MODEL
HAIKU = "claude-haiku-4-5-20251001"        # csv_import.AI_MODEL
SYSTEM_BUDGET_MICRO = 10_000_000           # "system" helpers, the whole app, a month ($10)
APP_NAME = "Northwend"


@dataclass(frozen=True)
class HelperSpec:
    name: str              # also its row in ai_spend
    model: str
    max_tokens: int        # an answer's length, never more
    effort: str | None     # output_config effort, or None to leave it unset
    thinking: bool         # adaptive thinking
    kind: str              # the ai_usage kind: the allowance, the ceiling's gate, the wording
    bucket: str            # an individual's allowance: chat / decode (advisors: ai_usage.bucket_of), or system
    carries_dollars: bool  # could any input or output hold a dollar figure? Then ZDR first
    timeout: float         # seconds, for a client the gateway makes itself


# The register. carries_dollars is False for all six today: the chat, plan
# and prep send percentages only (context_card.py, advisor.portfolio_summary,
# meeting.facts_for_ai) and the column guesses send column names and cell
# kinds. Screenshot reads are the exception the policy has to settle (PLAN
# D1, AI_PLAN step 18): the images are sent whole, behind the reader's own
# consent line and the screenshot_ai flag (off on the live copy). They stay
# unmarked so nothing changes until the owner decides; marking them True turns
# them off on hosted copies until AI_ZDR is set.
HELPERS = {
    "chat": HelperSpec("chat", SONNET, 2500, "medium", True, "chat", "chat", False, 600.0),
    "plan": HelperSpec("plan", SONNET, 4000, "medium", True, "plan", "chat", False, 600.0),
    "prep": HelperSpec("prep", SONNET, 2000, "low", True, "prep", "chat", False, 600.0),
    "screenshot": HelperSpec("screenshot", SONNET, 4000, None, False, "screenshot", "decode",
                             False, 90.0),
    "csv": HelperSpec("csv", HAIKU, 400, None, False, "csv", "decode", False, 30.0),
    "txn": HelperSpec("txn", HAIKU, 400, None, False, "csv", "decode", False, 30.0),
}

# the cache layout (step 9): the shared block lives an hour, the person's card
# and the conversation's tail the usual five minutes (longer ones come first)
SHARED_CACHE = {"type": "ephemeral", "ttl": "1h"}
CARD_CACHE = {"type": "ephemeral"}
TAIL_CACHE = {"type": "ephemeral"}


class Refused(anthropic.AnthropicError):
    """The gateway didn't make the call. `why`: "allowance", "unconfirmed",
    "resting", "closed", "paused", "zdr" or "unchecked" (the allowance
    couldn't be read - it fails closed); `calm_text`: the one
    sentence to show (no figures, never "limit" or "cost" for the ceiling)."""

    def __init__(self, why: str, calm_text: str):
        super().__init__(why)
        self.why = why
        self.calm_text = calm_text


def spec_for(helper: str) -> HelperSpec:
    try:
        return HELPERS[helper]
    except KeyError:
        raise ValueError(f"unknown AI helper: {helper!r} - add it to ai_gateway.HELPERS") from None


def _feature(spec: HelperSpec) -> str:
    return ai_spend.FEATURES.get(spec.kind) or f"Ask {APP_NAME}"


# ---- the checks --------------------------------------------------------------- #

def check_zdr(spec: HelperSpec) -> None:
    if spec.carries_dollars and settings.hosted() and not settings.ai_zdr():
        raise Refused("zdr", f"{_feature(spec)} isn't available right now.")


def system_spent(conn, now: datetime | None = None) -> int:
    """This month's spend on "system" helpers (no person), micro-dollars."""
    names = [s.name for s in HELPERS.values() if s.bucket == "system"]
    if not names:
        return 0
    row = conn.execute(
        "SELECT COALESCE(SUM(cost_micro), 0) AS n FROM ai_spend WHERE month = ? AND helper IN ("
        + ", ".join("?" for _ in names) + ")", (ai_spend.month_of(now), *names)).fetchone()
    return int(row["n"] or 0)


def check(spec: HelperSpec, user_id: int | None, *, conversation_open: bool = False,
          followup: bool = False, now: datetime | None = None) -> str:
    """Raise Refused unless `spec` may run now for `user_id`; returns the
    month's level (ai_spend). Without a database (ai_spend.use_db not called:
    scripts, unit tests) there is nothing to check. `followup`: another tool
    round of a message already allowed - the person's allowance isn't asked
    again mid-answer, the month's level still is."""
    db = ai_spend.sink_db()
    if not db:
        return ai_spend.NORMAL
    from portfolio import connect
    try:
        conn = connect(db)
        try:
            level = ai_spend.level(conn, now)
            if spec.bucket == "system":
                st = {"ok": system_spent(conn, now) < SYSTEM_BUDGET_MICRO,
                      "resets": ai_spend.resets_on(now)}
                if not st["ok"]:
                    st["resting_why"] = "resting"
            elif user_id is None or followup:
                st = {"ok": True, "resets": ai_spend.resets_on(now)}
            else:
                st = ai_usage.status(conn, user_id, spec.kind, now)
        finally:
            conn.close()
    except Exception:
        # the allowance can't be read: no call (fail closed), one calm line
        raise Refused("unchecked", f"{_feature(spec)} isn't available right now.") from None
    st = ai_spend.apply(st, level, spec.kind, conversation_open=conversation_open or followup)
    if not st["ok"]:
        why = st.get("resting_why") or ("unconfirmed" if st.get("unconfirmed") else "allowance")
        raise Refused(why, ai_usage.used_up_text(st, spec.kind, APP_NAME))
    return level


# ---- the request -------------------------------------------------------------- #

def library_text() -> str:
    """Northwend's own guide for the shared block (AI_PLAN 5.1): ai_library's
    block_text() once that module exists, else nothing. The same for
    everyone, so it never breaks the shared cache."""
    try:
        import ai_library
    except ImportError:
        return ""
    text = getattr(ai_library, "block_text", None)
    return (text() if callable(text) else "") or ""


def build_request(spec: HelperSpec, *, messages: list, system=None, shared: str | None = None,
                  card: str | None = None, tools=None, max_tokens: int | None = None,
                  effort: str | None = None, tail_cache: bool = False) -> dict:
    """The API request for `spec`. With `shared` (the chat): tools first, then
    system block 1 - `shared` and the library, the same for everyone, cached
    an hour - then block 2, the person's rendered ContextCard (`card`),
    cached for the conversation, then the messages with automatic caching on
    their tail. Otherwise `system` goes as given. `max_tokens` and `effort`
    may only shorten an answer (the month's level)."""
    req = {"model": spec.model,
           "max_tokens": min(max_tokens or spec.max_tokens, spec.max_tokens),
           "messages": messages}
    if tools:
        req["tools"] = list(tools)
    if shared is not None:
        library = library_text()
        blocks = [{"type": "text", "text": shared + ("\n\n" + library if library else ""),
                   "cache_control": dict(SHARED_CACHE)}]
        if card:
            blocks.append({"type": "text", "text": card, "cache_control": dict(CARD_CACHE)})
        req["system"] = blocks
        tail_cache = True
    elif system is not None:
        req["system"] = system
    if tail_cache:
        req["cache_control"] = dict(TAIL_CACHE)
    if spec.thinking:
        req["thinking"] = {"type": "adaptive"}
    if effort or spec.effort:
        req["output_config"] = {"effort": effort or spec.effort}
    return req


def _client(spec: HelperSpec):
    return anthropic.Anthropic(api_key=settings.get("ANTHROPIC_API_KEY", env_file=True) or None,
                               timeout=spec.timeout)


# ---- the call ----------------------------------------------------------------- #

def call(helper: str, *, messages: list, user_id: int | None = None, system=None,
         shared: str | None = None, card: str | None = None, tools=None, stream: bool = False,
         client=None, max_tokens: int | None = None, effort: str | None = None,
         conversation_open: bool = False, followup: bool = False):
    """Make one call for `helper` on behalf of `user_id` (the signed-in login -
    an advisor in a client's account is counted as the advisor). Returns the
    API's message; with stream=True, a generator that yields the answer's
    text as it comes and returns the final message (`msg = yield from
    call(...)`). Raises Refused when it may not run, and the SDK's own
    errors when the call fails (nothing is counted then)."""
    spec = spec_for(helper)
    check_zdr(spec)
    level = check(spec, user_id, conversation_open=conversation_open, followup=followup)
    if spec.kind == "chat":
        lower = ai_spend.chat_settings(level)
        if lower:
            max_tokens = min(max_tokens or spec.max_tokens, lower["max_tokens"])
            effort = lower["effort"]
    request = build_request(spec, messages=messages, system=system, shared=shared, card=card,
                            tools=tools, max_tokens=max_tokens, effort=effort)
    client = client or _client(spec)
    if stream:
        return _streamed(client, request, spec, user_id)
    message = client.messages.create(**request)
    _record(spec, message, user_id)
    return message


def _streamed(client, request: dict, spec: HelperSpec, user_id: int | None):
    with client.messages.stream(**request) as stream:
        for event in stream:
            if event.type == "text":
                yield event.text
        message = stream.get_final_message()
    _record(spec, message, user_id)
    return message


def _record(spec: HelperSpec, message, user_id: int | None) -> None:
    """Token counts and cost only (ai_spend.note never raises)."""
    also = None
    if user_id is not None and spec.bucket != "system":
        def also(conn, cost):
            ai_usage.add_cost(conn, user_id, spec.kind, cost)
    ai_spend.note(message, spec.name, spec.model, also=also)


# ---- the write rule: memory, saved on the person's behalf ------------------------ #

def may_keep_memory(login_id: int | None, account_id: int | None) -> bool:
    """The guide reads and keeps notes only in the person's own account - an
    advisor in a client's account never reads or writes the client's notes
    (AI_PLAN section 6)."""
    return login_id is not None and login_id == account_id


def save_memory(conn, *, login_id: int, account_id: int, notes) -> bool:
    """Save the chat's proposed notes (advisor.MemoryNote, already typed and
    scrubbed) to the person's own row. False, and nothing written, unless
    they're in their own account."""
    if not may_keep_memory(login_id, account_id):
        return False
    import advisor
    advisor.save_notes(conn, account_id, notes)
    return True
