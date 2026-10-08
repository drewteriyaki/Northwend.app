# Part of dashboard.py, which runs this file with _view("news_feed") at the
# point where this code used to sit, in dashboard.py's own namespace: the names
# here (st, DB, USER_ID, PAGE, the helpers...) are dashboard.py's, and what
# this defines is visible there afterwards. See _view() in dashboard.py.
#
# Your news (flag news_feed, flags.FEATURES - this whole file is skipped while
# it's off): headlines from news sources about the tickers this account holds
# or watches (news_feed.py picks them from what the hourly job stored).
# - Home (views/dashboard_page.py calls render_news_card): "News on what you
#   own", a few headlines and a way to the rest.
# - Money's News tab (PAGE "News", one of MONEY_PAGES): the rest, up to
#   news_feed.LIMIT.
# Each story: ticker, headline linking to the source (a new tab), source, how
# long ago. Never Finnhub's summary or article text, never the person's own
# figures beside a headline, nothing to act on. NEWS_ROWS is read in
# dashboard.py with the history (one query); nothing here waits on Finnhub.
# ruff: noqa: F821

NEWS_NOTE = ("Headlines from news sources about what you hold. Northwend doesn't write "
             "them or say what to do about them.")
NEWS_HOW = (f"Up to {news_feed.PER_TICKER} stories for each of your holdings and watched "
            f"tickers from the last {news_feed.RECENT_DAYS} days, newest first. A story "
            "several sources reported is shown once. Company press releases are left out. "
            "Checked about once an hour.")
NEWS_NONE = (f"No headlines about what you hold or watch from the last "
             f"{news_feed.RECENT_DAYS} days. Just added something? Its headlines can take "
             "up to an hour to appear.")


def _nf_md(text):
    """Text for st.markdown: nothing in a headline is read as formatting."""
    out = str(text or "")
    for ch in "\\`*_[]<>#|~$":
        out = out.replace(ch, "\\" + ch)
    return out


def _nf_url(url):
    """A link that can't break out of markdown's (...)."""
    return str(url).strip().replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def _nf_story(s, now):
    """One story: its tickers, the headline (a link to the source - Streamlit
    opens it in a new tab), then the source and how long ago."""
    chips = " ".join(f":gray-badge[{_nf_md(t)}]" for t in s["tickers"][:3])
    st.markdown(f"{chips} [{_nf_md(s['headline'])}]({_nf_url(s['url'])})")
    also = s["sources"] - 1
    st.caption(_nf_md(s["source"]) + " · " + news_feed.ago(s["when"], now)
               + (f" · also reported by {also} more source{'s' if also > 1 else ''}"
                  if also > 0 else ""))


def render_news_card(rows):
    """Home: "News on what you own" - a few headlines, then a way to the rest."""
    now = datetime.now(timezone.utc)
    picked = news_feed.pick(rows, now=now)
    with st.container(border=True, key="news_card"):
        st.markdown("#### News on what you own")
        st.caption(NEWS_NOTE)
        if not picked:
            st.caption(NEWS_NONE)
            return
        for s in picked[:news_feed.HOME_LIMIT]:
            _nf_story(s, now)
        if "News" in PAGES:
            st.button(f"All news ({len(picked)})" if len(picked) > news_feed.HOME_LIMIT
                      else "Open News", key="news_all", type="tertiary", on_click=_go,
                      args=("News",), icon=":material/newspaper:")


if PAGE == "News":
    with _page_main():   # Money's main card (dashboard._money_parts)
        _nf_now = datetime.now(timezone.utc)
        _nf_picked = news_feed.pick(NEWS_ROWS, now=_nf_now)
        st.caption(NEWS_NOTE)
        if not _my_tickers:
            st.caption("News shows up here for what you hold or watch - add holdings, or a ticker "
                       "to your watchlist.")
        elif not _nf_picked:
            st.caption(NEWS_NONE)
        else:
            for _i, _s in enumerate(_nf_picked):
                with st.container(key=f"news_row_{_i}"):
                    _nf_story(_s, _nf_now)
        st.caption(NEWS_HOW)
