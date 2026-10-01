"""AI Assistant: an educational investing chatbot for advisors and new investors.

Pure logic, no Streamlit, so everything here is unit-testable; dashboard.py's
_render_assistant() owns the UI.

What leaves the machine: portfolio_summary() builds the only holdings data
the model sees - tickers, names, asset types, sectors, and percentages. It
never includes dollar amounts, share counts, or account names.

Memory: the assistant keeps short notes per account (investor_profiles.
ai_memory) through its save_memory tool, and gets them back in the system
prompt next time. The app never displays them.
"""

from __future__ import annotations

import metrics as M
from allocation import CONCENTRATION_PCT, allocate
from asset_classes import describe, from_asset_type

MODEL = "claude-sonnet-5"
MAX_TOKENS = 16000
MAX_TOOL_ROUNDS = 4

RISK_LEVELS = ("conservative", "moderate", "aggressive")
EXPERIENCE_LEVELS = ("new", "some", "experienced")

GOAL_OPTIONS = ("Retirement", "Build long-term wealth", "Buy a home", "Pay for education",
                "Generate income", "Preserve what I have", "Save for a big purchase",
                "Emergency savings")
PREFERENCE_OPTIONS = ("Low-cost index funds", "Hands-off / set and forget", "Dividend income",
                      "Sustainable (ESG) investing", "Avoid individual stocks",
                      "Tax efficiency", "Keep some cash on hand")

# field -> label shown to the model, in the PDF, and in the form
PROFILE_FIELDS = {
    "goal": "Long-term goals",
    "time_horizon_years": "Time horizon (years)",
    "target_return_pct": "Target annual return %",
    "risk_tolerance": "Risk tolerance",
    "drawdown_reaction": "If the portfolio fell 20% in a month",
    "experience": "Investing experience",
    "age_range": "Age",
    "income_stability": "Income stability",
    "emergency_fund": "Emergency fund",
    "high_interest_debt": "High-interest debt",
    "employer_match": "Employer retirement match",
    "contributions": "Adding money",
    "withdrawal_needs": "Withdrawals in the next 3 years",
    "preferences": "Preferences",
    "notes": "Other notes",
}
# pick-one answers
CHOICES = {
    "risk_tolerance": RISK_LEVELS,
    "drawdown_reaction": ("Sell everything", "Sell some", "Hold and wait", "Buy more"),
    "experience": EXPERIENCE_LEVELS,
    "age_range": ("Under 25", "25-34", "35-44", "45-54", "55-64", "65 or older"),
    "income_stability": ("Very stable", "Mostly stable", "Varies a lot", "Not working or retired"),
    "emergency_fund": ("6+ months of expenses", "3-6 months", "Under 3 months", "None"),
    "high_interest_debt": ("None", "Some", "A lot"),
    "employer_match": ("Yes, and I get the full match", "Yes, but I'm not getting all of it",
                       "No match or no plan", "Not sure"),
    "contributions": ("Monthly or more", "A few times a year", "Rarely", "Withdrawing regularly"),
    "withdrawal_needs": ("None planned", "Small amounts", "A large amount"),
}
# pick-any answers, stored as one "; "-joined string
MULTI_CHOICES = {"goal": GOAL_OPTIONS, "preferences": PREFERENCE_OPTIONS}
MULTI_SEP = "; "
# target return, preferences, and the rest are useful but not worth holding
# up advice for; notes is the user's own free text
REQUIRED_PROFILE_FIELDS = ("goal", "time_horizon_years", "risk_tolerance", "drawdown_reaction",
                           "experience", "age_range", "income_stability", "emergency_fund")

# The assistant's own notes between conversations, kept on the profile row
# but never shown in the app.
MEMORY_MAX_CHARS = 1500

REFUSAL_TEXT = "Sorry - I can't help with that one. Try asking it a different way."


# --------------------------------------------------------------------------- #
# profile storage
# --------------------------------------------------------------------------- #
def get_profile(conn, user_id: int) -> dict:
    row = conn.execute("SELECT * FROM investor_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if row is None:
        return {f: None for f in PROFILE_FIELDS}
    return {f: row[f] for f in PROFILE_FIELDS}


def save_profile(conn, user_id: int, fields: dict, *, replace: bool = False) -> dict:
    """Merge `fields` into the saved profile and return the result. A None
    value leaves that field alone, unless `replace` is set (the profile form,
    where emptying a field means clearing it)."""
    profile = get_profile(conn, user_id)
    if replace:
        profile = {f: fields.get(f) for f in PROFILE_FIELDS}
    else:
        profile.update({k: v for k, v in fields.items() if k in PROFILE_FIELDS and v is not None})
    cols = list(PROFILE_FIELDS)
    conn.execute(
        f"INSERT INTO investor_profiles (user_id, {', '.join(cols)}, updated_at) "
        f"VALUES (?, {', '.join('?' for _ in cols)}, datetime('now')) "
        f"ON CONFLICT(user_id) DO UPDATE SET "
        + ", ".join(f"{c} = excluded.{c}" for c in cols)
        + ", updated_at = datetime('now')",
        (user_id, *(profile[c] for c in cols)))
    conn.commit()
    return profile


def missing_fields(profile: dict) -> list[str]:
    return [f for f in REQUIRED_PROFILE_FIELDS if profile.get(f) in (None, "")]


def split_multi(value) -> list[str]:
    """A pick-any field's stored string as a list."""
    return [v.strip() for v in (value or "").split(MULTI_SEP.strip()) if v.strip()]


def get_memory(conn, user_id: int) -> str:
    row = conn.execute("SELECT ai_memory FROM investor_profiles WHERE user_id = ?",
                       (user_id,)).fetchone()
    return (row["ai_memory"] or "") if row else ""


def save_memory(conn, user_id: int, text: str) -> None:
    conn.execute(
        "INSERT INTO investor_profiles (user_id, ai_memory, updated_at) "
        "VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(user_id) DO UPDATE SET ai_memory = excluded.ai_memory",
        (user_id, text))
    conn.commit()


# --------------------------------------------------------------------------- #
# the two tools: profile answers, and the assistant's own notes
# --------------------------------------------------------------------------- #
def _nullable(schema: dict) -> dict:
    return {"anyOf": [schema, {"type": "null"}]}


def _profile_tool_props() -> dict:
    props = {
        "time_horizon_years": {"type": ["integer", "null"],
                               "description": "Years until they need the money."},
        "target_return_pct": {"type": ["number", "null"],
                              "description": "Annual return they're aiming for, in percent."},
    }
    for field, options in MULTI_CHOICES.items():
        props[field] = {**_nullable({"type": "array",
                                     "items": {"type": "string", "enum": list(options)}}),
                        "description": f"{PROFILE_FIELDS[field]}: every option that applies."}
    for field, options in CHOICES.items():
        props[field] = {**_nullable({"type": "string", "enum": list(options)}),
                        "description": PROFILE_FIELDS[field]}
    return props


# notes stays out: it's the user's own free text, and the assistant's
# context goes in its memory instead
TOOL_PROFILE_FIELDS = tuple(f for f in PROFILE_FIELDS if f != "notes")

PROFILE_TOOL = {
    "name": "update_investor_profile",
    "description": (
        "Save profile answers the user has given you. Call it as soon as the user states "
        "any of these; pass null for anything they haven't mentioned in this message so it "
        "stays unchanged. Pick the closest option; put detail that doesn't fit an option "
        "in your notes (save_memory) instead."
    ),
    "strict": True,
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": _profile_tool_props(),
        "required": list(TOOL_PROFILE_FIELDS),
        "additionalProperties": False,
    },
}

MEMORY_TOOL = {
    "name": "save_memory",
    "description": (
        "Replace your private notes about this person, which you'll see at the start of "
        "future conversations. Pass the complete updated notes, not just what's new."
    ),
    "strict": True,
    "eager_input_streaming": True,
    "input_schema": {
        "type": "object",
        "properties": {"notes": {"type": "string",
                                 "description": f"Terse notes, under {MEMORY_MAX_CHARS} characters."}},
        "required": ["notes"],
        "additionalProperties": False,
    },
}


def validate_profile_input(args) -> tuple[dict | None, str]:
    """(fields_to_save, error). Only non-null, valid values are returned.
    Eager input streaming means the API doesn't validate the tool input for
    us, so this is the real check."""
    if not isinstance(args, dict):
        return None, "input must be an object"
    unknown = set(args) - set(TOOL_PROFILE_FIELDS)
    if unknown:
        return None, f"unknown fields: {', '.join(sorted(unknown))}"
    out = {}
    for field, value in args.items():
        if value is None:
            continue
        if field == "time_horizon_years":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 80:
                return None, "time_horizon_years must be between 1 and 80"
            out[field] = int(value)
        elif field == "target_return_pct":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 50:
                return None, "target_return_pct must be between 0 and 50"
            out[field] = float(value)
        elif field in MULTI_CHOICES:
            options = MULTI_CHOICES[field]
            if not isinstance(value, list) or any(v not in options for v in value):
                return None, f"{field} must be a list drawn from: {', '.join(options)}"
            if value:
                out[field] = MULTI_SEP.join(o for o in options if o in value)
        else:
            if value not in CHOICES[field]:
                return None, f"{field} must be one of: {', '.join(CHOICES[field])}"
            out[field] = value
    return out, ""


def validate_memory_input(args) -> tuple[str | None, str]:
    """(notes_to_save, error)."""
    if not isinstance(args, dict) or set(args) != {"notes"} or not isinstance(args["notes"], str):
        return None, "input must be {\"notes\": <text>}"
    text = args["notes"].strip()
    if len(text) > MEMORY_MAX_CHARS:
        return None, (f"notes are {len(text)} characters - shorten them to under "
                      f"{MEMORY_MAX_CHARS} and save again")
    return text, ""


# --------------------------------------------------------------------------- #
# what the model is told
# --------------------------------------------------------------------------- #
def _pct(v):
    return "n/a" if v is None else f"{v:.1f}%"


def _num(v):
    return "n/a" if v is None else f"{v:.2f}"


def portfolio_summary(contexts: list[dict], cash_by_account: dict,
                      splits: dict | None = None) -> str:
    """Weights-only description of the holdings. `contexts` is dashboard.py's
    per-position metric context list; `splits` is asset_classes.splits()."""
    if not contexts:
        return "No holdings yet - this person hasn't imported any positions."

    splits = splits or {}
    alloc = allocate([c["pos"] for c in contexts], cash_by_account, splits)
    rows = []
    for c in contexts:
        split = splits.get(c["pos"]["symbol"]) or from_asset_type(c["pos"].get("asset_type"))
        rows.append((
            M.value("pct_of_portfolio", c) or 0.0,
            f"- {c['pos']['symbol']} ({M.value('description', c) or 'unknown'}): "
            f"{_pct(M.value('pct_of_portfolio', c))} of portfolio; "
            f"holds {describe(split)}; "
            f"type {M.value('asset_type', c) or 'unknown'}; "
            f"sector {M.value('sector', c) or 'n/a'}; "
            f"gain/loss {_pct(M.value('unrealized_pct', c))}; "
            f"dividend yield {_pct(M.value('div_yield_pct', c))}; "
            f"beta {_num(M.value('beta', c))}; P/E {_num(M.value('pe_ttm', c))}",
        ))
    rows.sort(key=lambda r: r[0], reverse=True)

    mix = ", ".join(f"{r['label']} {_pct(r['pct'])}" for r in alloc["by_asset_class"])
    n_accounts = len({c["pos"].get("account") for c in contexts} | set(cash_by_account))
    return "\n".join([
        f"{len(contexts)} positions across {n_accounts} account(s).",
        f"Asset mix: {mix}.",
        "Positions, largest first:",
        *(r[1] for r in rows),
    ])


def system_prompt(profile: dict, summary: str, memory: str = "") -> str:
    """`memory` is the assistant's own saved notes (get_memory)."""
    known = [f"- {PROFILE_FIELDS[f]}: {profile[f]}" for f in PROFILE_FIELDS
             if profile.get(f) not in (None, "")]
    missing = missing_fields(profile)

    parts = [
        "You are Northwend, the guide inside the Northwend portfolio-tracking website - "
        "like the helpful guide character in a game who points a newcomer the right way and "
        "offers hints, without taking over. If asked who you are, say you're Northwend, the "
        "app's guide. The people "
        "you talk to are financial advisors working with clients, and individual investors - "
        "often new ones who find investing overwhelming. Your job is to understand their "
        "situation, then help them build or improve a diversified portfolio that fits it.",

        "Keep it educational. Explain your reasoning in plain language, tie suggestions to "
        "their stated goals and risk tolerance, and prefer categories of investment (broad "
        "index funds, bond funds, international exposure, and so on) over single-stock picks. "
        "You may name specific funds or tickers as examples, but frame them as options to "
        "research, not instructions to buy. You are not a licensed financial advisor, and "
        "this isn't personalized financial advice - say so briefly when you make "
        "recommendations, without repeating it in every message.",

        "## Their profile\n" + ("\n".join(known) if known else "Nothing saved yet."),
    ]
    if missing:
        parts.append(
            "Still unknown: " + ", ".join(PROFILE_FIELDS[f] for f in missing) + ". "
            "Before giving portfolio recommendations, ask about these conversationally, one "
            "or two at a time. You can still answer a direct general question first. If "
            "several are missing, mention they can also answer them quickly in the "
            "\"Your investing profile\" form above the chat."
        )
    parts += [
        "Whenever they tell you something that belongs in their profile, call the "
        "update_investor_profile tool so it's saved for next time.",

        "## Your notes from earlier conversations\n"
        +(memory.strip() or "None yet - this is your first conversation with them."),

        "These notes carry over between conversations; the app doesn't display them. When "
        "you learn something worth remembering that the profile doesn't hold - specifics "
        "behind their goals (dates, amounts, life events), worries, decisions they made, "
        "what you've already recommended or explained, things to follow up on - call "
        "save_memory with the complete updated notes. Keep them terse (fragments, no full "
        f"sentences), well under {MEMORY_MAX_CHARS} characters; merge and drop outdated "
        "items rather than appending. Leave out profile answers, open profile questions, and "
        "holdings - you get those fresh every time. Skip it for small talk, and don't keep "
        "anything they ask you to forget. If asked, you can say you "
        "keep brief notes between conversations.",

        "## Their current holdings\n" + summary,

        "When reviewing holdings, look for: any single position above "
        f"{CONCENTRATION_PCT:.0f}% of the portfolio; funds that overlap heavily in what they "
        "hold; sector concentration; overall risk (beta, asset mix) compared with their risk "
        "tolerance and time horizon; and positions with large losses worth a second look.",

        "## Limits\n"
        "You only see holdings as percentages - no dollar amounts, share counts, or account "
        "names. If a question needs amounts, ask for them. You have no live news or prices "
        "beyond the figures above, and you judge overlap between funds from general knowledge "
        "of what they typically hold, not live holdings data; say so when it matters.",
    ]
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# talking to the model
# --------------------------------------------------------------------------- #
def stream_reply(client, history: list, system: str, on_profile_update, on_memory=None):
    """Yield the assistant's reply as text chunks. `history` is the API
    message list and is extended in place (assistant turns, tool results).
    `on_profile_update(fields)` is called with validated profile fields, and
    `on_memory(text)` with the assistant's new notes, whenever it uses those
    tools."""
    for _ in range(MAX_TOOL_ROUNDS):
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=history,
                tools=[PROFILE_TOOL, MEMORY_TOOL],
                thinking={"type": "adaptive"},
                output_config={"effort": "medium"},
                cache_control={"type": "ephemeral"},
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        yield event.text
                message = stream.get_final_message()
        except ValueError:
            # tool input the SDK couldn't parse at all
            yield "\n\n(Something went wrong saving your profile - please try again.)"
            return

        history.append({"role": "assistant", "content": message.content})

        if message.stop_reason == "refusal":
            yield REFUSAL_TEXT
            return
        tool_uses = [b for b in message.content if b.type == "tool_use"]
        if message.stop_reason != "tool_use" or not tool_uses:
            return

        results = []
        for block in tool_uses:
            if block.name == MEMORY_TOOL["name"]:
                text, error = validate_memory_input(block.input)
                if not error and on_memory is not None:
                    on_memory(text)
                saved = "Notes saved."
            else:
                fields, error = validate_profile_input(block.input)
                if not error:
                    on_profile_update(fields)
                saved = "Saved to their profile."
            if error:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "is_error": True, "content": error})
            else:
                results.append({"type": "tool_result", "tool_use_id": block.id,
                                "content": saved})
        history.append({"role": "user", "content": results})
