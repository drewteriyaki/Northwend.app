"""The ContextCard (docs/AI_PLAN.md section 3, step 8): everything Ask
Northwend may know about a person, and the only way their account data
reaches the chat's prompt. Pure logic, no Streamlit, no database.

Every field has a narrow type - a choice from advisor.CHOICES, a whole
percent, a validated ticker, a count, a fixed key - and the dataclasses check
it when they're made, so a card physically can't hold a dollar amount, a
share count, a cost, an account name or number, the file's description text,
the profile's "Other notes", or anyone's name or email (section 3.2). A fund's
name comes from market data (security_info), scrubbed of figures, never from
the person's file. Weights are whole percents.

The card is made once when a conversation starts and kept in the session
(for_conversation), so live prices moving during the conversation don't
change it: the prompt's second block stays byte-identical turn to turn and
its cache keeps working (AI_PLAN 3.5, ai_gateway.build_request).

Scopes: SELF (the person in their own account: their notes included) and
ADVISOR_FULL (an advisor in a client's account: the same minus the notes -
the advisor's conversation never reads or keeps the client's notes).

Client mode (AI_PLAN 7.3, step 13): a person who works with an advisor
(dashboard.CLIENT_MODE, talking in their own account) gets client_mode and
their advisor's label - the name and firm the advisor shows clients, cleaned
like a fund's name, never a login or an email. The card shows the label in
its <advisor> part, and render() adds ai_policy's client rule after the
closing </card> tag: the rule is part of this person's own (second) block,
so the shared first block stays identical for everyone and its cache holds.
An advisor talking in a client's account is the advisor, not the client:
no client mode there (the card's notes part says who is talking).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import advisor
import metrics as M
from allocation import allocate
from asset_classes import CLASSES, from_asset_type
from csv_import import _is_ticker

SELF, ADVISOR_FULL = "self", "advisor_full"
SCOPES = (SELF, ADVISOR_FULL)
# where they are on Northwend's route (route.py): its two stages, or past them
STAGES = {"learn": "Learn - the first stage of Northwend's route (learning the basics)",
          "invest": "Start investing - choosing a brokerage, opening an account, a first "
                    "investment and bringing it into Northwend",
          "investing": "Investing - their own holdings are in Northwend"}
# (label, under this many years) - the last has no upper end
TIMELINES = (("under 3 years", 3), ("3 to 5 years", 6), ("6 to 10 years", 11),
             ("11 to 20 years", 21), ("more than 20 years", None))
TOP_HOLDINGS = 15
NAME_MAX = 60
LABEL_MAX = 80             # an advisor's label: "Jane Doe, Doe Planning"
# what the client rule calls the advisor - the label itself is data, in the
# card's <advisor> part, so the instruction after the card holds no typed text
ADVISOR_REF = "their advisor (named in the card's <advisor> part)"
STORE_KEY = "chat_card"   # in session state: {"for": account id, "text": rendered card}

_FIGURE = re.compile(r"[$€£¥]|\b\d{1,3}(?:,\d{3})+\b")
_LONG_DIGITS = re.compile(r"\d{4,}")
_YEAR = re.compile(r"(?:19|20)\d\d")


def _pct(v) -> int:
    """A whole percent, 0-100."""
    try:
        return max(0, min(100, int(round(float(v)))))
    except (TypeError, ValueError):
        return 0


def _is_pct(v, low: int = 0, high: int = 100) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and low <= v <= high


def _safe_text(s) -> bool:
    """Text that can't carry a figure or open a tag: no currency sign, no
    grouped number, no run of 4+ digits that isn't a year."""
    if not isinstance(s, str) or "<" in s or ">" in s or "\n" in s or _FIGURE.search(s):
        return False
    return all(_YEAR.fullmatch(m.group(0)) for m in _LONG_DIGITS.finditer(s))


def clean_name(raw) -> str:
    """A fund's name from market data, safe for the card: one line, at most
    NAME_MAX characters, amounts and account numbers taken out
    (advisor.scrub_memory), no tag brackets. "name unknown" when nothing is
    left."""
    text = " ".join(str(raw or "").replace("<", " ").replace(">", " ").split())[:NAME_MAX * 2]
    text = " ".join(_FIGURE.sub("", advisor.scrub_memory(text)).split())
    if len(text) > NAME_MAX:   # cut at a word, after scrubbing (which can lengthen it)
        text = text[:NAME_MAX].rsplit(" ", 1)[0] if " " in text[:NAME_MAX] else text[:NAME_MAX]
    return text if text and _safe_text(text) else "name unknown"


def clean_advisor_label(name, firm=None) -> str | None:
    """The advisor's label for the card: "Name, Firm" as the advisor shows
    it to clients - one line, at most LABEL_MAX characters, no figures, no
    tag brackets, never an email. None without a clean name."""
    def clean(raw) -> str:
        text = " ".join(str(raw or "").replace("<", " ").replace(">", " ").split())
        ok = text and "@" not in text and _safe_text(text) and advisor.scrub_memory(text) == text
        return text if ok else ""
    who, where = clean(name), clean(firm)
    if not who:
        return None
    return (f"{who}, {where}" if where else who)[:LABEL_MAX].rstrip(" ,") or None


def _classes(pairs) -> bool:
    return all(isinstance(p, tuple) and len(p) == 2 and p[0] in CLASSES and _is_pct(p[1])
               for p in pairs)


@dataclass(frozen=True)
class HoldingLine:
    ticker: str                             # a validated ticker (csv_import._is_ticker)
    name: str                               # market data's name, clean_name()
    kind: tuple[tuple[str, int], ...]       # what it holds: (asset class, whole %)
    weight: int                             # whole % of the portfolio

    def __post_init__(self):
        if not (isinstance(self.ticker, str) and _is_ticker(self.ticker)):
            raise ValueError("not a ticker")
        if not (_safe_text(self.name) and len(self.name) <= NAME_MAX):
            raise ValueError("a holding's name must be clean_name()'s")
        if not (_classes(self.kind) and _is_pct(self.weight)):
            raise ValueError("kind and weight are whole percents by asset class")


@dataclass(frozen=True)
class ContextCard:
    scope: str                               # SELF or ADVISOR_FULL
    goals: tuple[str, ...]                   # advisor.GOAL_OPTIONS
    timeline: str | None                     # a TIMELINES label
    answers: tuple[tuple[str, str], ...]     # (field, choice) from advisor.CHOICES
    preferences: tuple[str, ...]             # advisor.PREFERENCE_OPTIONS
    target_return: int | None                # whole %, 0-50
    unknown: tuple[str, ...]                 # profile fields still open (advisor.PROFILE_FIELDS keys)
    stage: str | None                        # a STAGES key
    mix: tuple[tuple[str, int], ...]         # actual mix by asset class, whole %
    target: tuple[tuple[str, int], ...]      # their own target mix, whole %
    band: int | None                         # their own drift band, points
    drift: tuple[tuple[str, int], ...]       # actual - target, whole points
    holdings: tuple[HoldingLine, ...]        # the largest TOP_HOLDINGS
    others: tuple[int, int]                  # (how many more, their whole % together)
    positions: int
    accounts: int
    notes: tuple[advisor.MemoryNote, ...]    # SELF only
    client_mode: bool = False                # works with an advisor (SELF only)
    advisor_label: str | None = None         # clean_advisor_label(), client mode only

    def __post_init__(self):
        ok = (
            self.scope in SCOPES
            and all(g in advisor.GOAL_OPTIONS for g in self.goals)
            and (self.timeline is None or self.timeline in {t for t, _ in TIMELINES})
            and all(isinstance(a, tuple) and len(a) == 2 and a[0] in advisor.CHOICES
                    and a[1] in advisor.CHOICES[a[0]] for a in self.answers)
            and all(p in advisor.PREFERENCE_OPTIONS for p in self.preferences)
            and (self.target_return is None or _is_pct(self.target_return, 0, 50))
            and all(f in advisor.PROFILE_FIELDS for f in self.unknown)
            and (self.stage is None or self.stage in STAGES)
            and _classes(self.mix) and _classes(self.target)
            and (self.band is None or _is_pct(self.band))
            and all(isinstance(d, tuple) and len(d) == 2 and d[0] in CLASSES
                    and _is_pct(d[1], -100, 100) for d in self.drift)
            and all(isinstance(h, HoldingLine) for h in self.holdings)
            and len(self.holdings) <= TOP_HOLDINGS
            and isinstance(self.others, tuple) and len(self.others) == 2
            and all(_is_pct(v, 0, 100_000) for v in self.others)
            and _is_pct(self.positions, 0, 100_000) and _is_pct(self.accounts, 0, 100_000)
            and all(isinstance(n, advisor.MemoryNote) for n in self.notes)
            and (self.scope == SELF or not self.notes)
            and isinstance(self.client_mode, bool)
            and (not self.client_mode or self.scope == SELF)
            and (self.advisor_label is None
                 or (self.client_mode and isinstance(self.advisor_label, str)
                     and clean_advisor_label(self.advisor_label) == self.advisor_label)))
        if not ok:
            raise ValueError("a ContextCard holds only its typed fields (AI_PLAN 3.1)")

    # ---- what the model reads --------------------------------------------- #
    def render(self) -> str:
        """Fixed, ordered text in section tags, so data never reads as a
        section of the prompt. The same card always renders the same text."""
        profile = []
        if self.goals:
            profile.append("Goals: " + "; ".join(self.goals))
        if self.timeline:
            profile.append(f"Time until they need the money: {self.timeline}")
        if self.target_return is not None:
            profile.append(f"Target annual return they set: {self.target_return}%")
        profile += [f"{advisor.PROFILE_FIELDS[f]}: {v}" for f, v in self.answers]
        if self.preferences:
            profile.append("Preferences: " + "; ".join(self.preferences))
        if not profile:
            profile.append("Nothing saved yet.")
        if self.unknown:
            profile.append("Still unknown: "
                           + ", ".join(advisor.PROFILE_FIELDS[f] for f in self.unknown))

        plan = []
        if self.target:
            plan.append("Their own target mix: " + _mix_text(self.target))
            if self.band is not None:
                plan.append(f"Their band: {self.band} points either way")
            if self.drift:
                plan.append("Actual minus target: " + ", ".join(
                    f"{k} {v:+d} points" for k, v in self.drift))
        else:
            plan.append("No target mix set.")

        if self.positions:
            holdings = [f"{self.positions} position{'s' if self.positions != 1 else ''} across "
                        f"{self.accounts} account{'s' if self.accounts != 1 else ''}.",
                        "Mix by asset class: " + (_mix_text(self.mix) or "unknown") + ".",
                        "Largest first (whole % of the portfolio):"]
            holdings += [f"- {h.ticker} ({h.name}): {h.weight}%; holds {_kind_text(h.kind)}"
                         for h in self.holdings]
            if self.others[0]:
                holdings.append(f"- {self.others[0]} other{'s' if self.others[0] != 1 else ''}, "
                                f"{self.others[1]}% together")
        else:
            holdings = ["No holdings yet - this person hasn't brought any in."]

        if self.scope == SELF:
            notes = advisor.notes_text(self.notes) or ("None yet - this is your first "
                                                       "conversation with them.")
        else:
            notes = ("Notes aren't kept in this conversation: you're talking with this "
                     "person's advisor, in their client's account.")
        parts = ["<card>",
                 "<profile>", *profile, "</profile>",
                 "<plan>", *plan, "</plan>",
                 "<holdings>", *holdings, "</holdings>"]
        if self.stage:
            parts += ["<route>", STAGES[self.stage], "</route>"]
        if self.client_mode:
            parts += ["<advisor>", "They work with an advisor: "
                      + (self.advisor_label or "name not shown") + ".", "</advisor>"]
        parts += ["<notes>", notes, "</notes>", "</card>"]
        if self.client_mode:
            # Northwend's own rule for this conversation, after the card (never
            # data): ai_policy's rule 10, pointing at the label in the card
            import ai_policy
            parts += ["", "## For this conversation",
                      ai_policy.client_rule(ADVISOR_REF)
                      + " When you point them to their advisor, use the advisor's name from "
                        "the card."]
        return "\n".join(parts)


def _mix_text(pairs) -> str:
    return ", ".join(f"{k} {v}%" for k, v in pairs)


def _kind_text(kind) -> str:
    if len(kind) == 1:
        return kind[0][0].lower()
    return " / ".join(f"{v}% {k.lower()}" for k, v in kind)


# ---- making one --------------------------------------------------------------- #

def timeline_of(years) -> str | None:
    try:
        y = float(years)
    except (TypeError, ValueError):
        return None
    if y <= 0:
        return None
    for label, under in TIMELINES:
        if under is None or y < under:
            return label
    return None


def _profile_parts(profile: dict) -> dict:
    """The allowlisted profile answers - the "Other notes" free text never."""
    p = profile or {}
    goals = tuple(g for g in advisor.split_multi(p.get("goal")) if g in advisor.GOAL_OPTIONS)
    prefs = tuple(x for x in advisor.split_multi(p.get("preferences"))
                  if x in advisor.PREFERENCE_OPTIONS)
    answers = tuple((f, p.get(f)) for f in advisor.CHOICES
                    if p.get(f) in advisor.CHOICES[f])
    target = p.get("target_return_pct")
    try:
        target = int(round(float(target))) if target not in (None, "") else None
    except (TypeError, ValueError):
        target = None
    return {"goals": goals, "timeline": timeline_of(p.get("time_horizon_years")),
            "answers": answers, "preferences": prefs,
            "target_return": target if target is not None and 0 <= target <= 50 else None,
            "unknown": tuple(advisor.missing_fields(
                {f: p.get(f) for f in advisor.PROFILE_FIELDS}))}


def _split(c: dict, splits: dict) -> tuple[tuple[str, int], ...]:
    pos = c.get("pos") or {}
    raw = splits.get(pos.get("symbol")) or from_asset_type(pos.get("asset_type"))
    parts = [(k, _pct(v * 100)) for k, v in sorted(raw.items(), key=lambda kv: -kv[1])
             if k in CLASSES and v >= 0.005]
    return tuple(p for p in parts if p[1] > 0) or (("Other", 100),)


def build(*, profile: dict, contexts: list, cash_by_account: dict, splits: dict | None = None,
          targets: dict | None = None, band=None, stage: str | None = None, memory: str = "",
          scope: str = SELF, client_mode: bool = False,
          advisor_label: str | None = None) -> ContextCard:
    """A card from what the page already holds: the profile row (only its
    answers), dashboard.py's position contexts (each one's symbol, account,
    asset type and live value - for weights and counts; the name is market
    data's, c["info"]["name"]), cash by account (amounts become percents
    here and go no further), asset_classes.splits(), their target mix
    ({class: %}) and band (points), the route stage, and the guide's saved
    notes (only kept for SELF). `client_mode`: the person works with an
    advisor (and is the one talking - SELF); `advisor_label`: the advisor's
    name and firm, as clean_advisor_label() makes it."""
    splits = splits or {}
    rows = [{"symbol": (c.get("pos") or {}).get("symbol"),
             "account": (c.get("pos") or {}).get("account"),
             "asset_type": (c.get("pos") or {}).get("asset_type"),
             "live_market_value": M.eff_mv(c) or 0.0} for c in contexts]
    alloc = allocate(rows, cash_by_account or {}, splits)
    total = alloc["portfolio_value"] or 0.0
    actual = {r["label"]: float(r["pct"] or 0.0) for r in alloc["by_asset_class"]
              if r["label"] in CLASSES}

    lines: dict[str, list] = {}
    others_n = others_w = 0.0
    for c, row in zip(contexts, rows):
        weight = row["live_market_value"] / total * 100 if total else 0.0
        ticker = str(row["symbol"] or "").strip().upper()
        if not _is_ticker(ticker):
            others_n, others_w = others_n + 1, others_w + weight
            continue
        if ticker in lines:
            lines[ticker][0] += weight
        else:
            info = c.get("info") or {}
            lines[ticker] = [weight, clean_name(info.get("name")), _split(c, splits)]
    ranked = sorted(lines.items(), key=lambda kv: -kv[1][0])
    for _t, (w, _n, _k) in ranked[TOP_HOLDINGS:]:
        others_n, others_w = others_n + 1, others_w + w
    holdings = tuple(HoldingLine(t, n, k, _pct(w)) for t, (w, n, k) in ranked[:TOP_HOLDINGS])

    target = {k: float(v) for k, v in (targets or {}).items()
              if k in CLASSES and v not in (None, "") and float(v) > 0}
    try:
        band_ = _pct(band) if band not in (None, "") else None
    except (TypeError, ValueError):
        band_ = None
    accounts = {row["account"] for row in rows} | set(cash_by_account or {})
    return ContextCard(
        scope=scope, **_profile_parts(profile),
        stage=stage if stage in STAGES else None,
        mix=tuple((k, _pct(actual[k])) for k in CLASSES if _pct(actual.get(k)) > 0),
        target=tuple((k, _pct(target[k])) for k in CLASSES if k in target),
        band=band_ if target else None,
        drift=tuple((k, max(-100, min(100, int(round(actual.get(k, 0.0) - target[k])))))
                    for k in CLASSES if k in target),
        holdings=holdings,
        others=(int(others_n), _pct(others_w)),
        positions=len(contexts),
        accounts=len(accounts) if contexts or cash_by_account else 0,
        notes=advisor.parse_notes(memory) if scope == SELF else (),
        client_mode=bool(client_mode) and scope == SELF,
        advisor_label=(clean_advisor_label(advisor_label)
                       if client_mode and scope == SELF else None))


def stage_of(*, has_real_holdings: bool, experience: str | None, managed: bool) -> str:
    """Where the person is: "investing" once their own holdings are in,
    else the route's stage (route.learn_first)."""
    import route
    if has_real_holdings:
        return "investing"
    return "learn" if route.learn_first(experience, managed) else "invest"


def for_conversation(store, account_id: int, make) -> tuple[str, bool]:
    """The conversation's card, rendered: made with make() when the
    conversation starts (or the account changes), then the same text from
    `store` (session state) every turn - live prices can't change it.
    Returns (text, made_now)."""
    held = store.get(STORE_KEY)
    if isinstance(held, dict) and held.get("for") == account_id and held.get("text"):
        return held["text"], False
    text = make().render()
    store[STORE_KEY] = {"for": account_id, "text": text}
    return text, True


def forget(store) -> None:
    """A new conversation gets a fresh card ("New conversation")."""
    store.pop(STORE_KEY, None)
