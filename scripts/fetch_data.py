"""
Fetches market data for the BAM vs Heijmans dashboard and writes data/data.json.

Runs on GitHub's servers (see .github/workflows/update-data.yml), so the
dashboard itself never has to call Yahoo or Google from the browser.

- Prices: Yahoo Finance daily closes for 5 years plus the latest quote.
- News: Google News RSS headlines that mention the company name.
- If a source fails, the last successfully fetched data is kept and the
  error is recorded, so the page can say how old the data is.
  Nothing is ever made up.
"""

import email.utils
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "data.json")

SYMBOLS = {"bam": "BAMNB.AS", "heij": "HEIJM.AS", "idx": "^AEX"}
NEWS = {
    "bam": ('"Koninklijke BAM" OR "BAM Groep" OR "bouwer BAM" OR "bouwbedrijf BAM"', re.compile(r"\bBAM\b")),
    "heij": ("Heijmans", re.compile(r"Heijmans", re.I)),
}
NEWS_MAX_AGE_DAYS = 60
META_KEYS = [
    "symbol", "currency", "regularMarketPrice", "regularMarketTime", "regularMarketVolume",
    "regularMarketDayHigh", "regularMarketDayLow", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "chartPreviousClose",
]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json,text/xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8",
}

COOKIES = http.cookiejar.CookieJar()
OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(COOKIES))
_crumb = None


def get(url, timeout=20):
    with OPENER.open(urllib.request.Request(url, headers=HEADERS), timeout=timeout) as r:
        return r.read()


def yahoo_crumb():
    """Pick up Yahoo's cookie and crumb like a browser visit; helps against HTTP 429."""
    global _crumb
    if _crumb:
        return _crumb
    try:
        get("https://fc.yahoo.com", 10)
    except Exception:
        pass  # answers 404 but sets the cookie
    try:
        crumb = get("https://query2.finance.yahoo.com/v1/test/getcrumb", 10).decode().strip()
        if crumb and "<" not in crumb and len(crumb) < 64:
            _crumb = crumb
    except Exception:
        pass
    return _crumb


def yahoo_chart(symbol):
    base = "https://{host}/v8/finance/chart/" + urllib.parse.quote(symbol) + "?range=5y&interval=1d&includePrePost=false"
    attempts = [("query1.finance.yahoo.com", False), ("query2.finance.yahoo.com", True), ("query1.finance.yahoo.com", True)]
    last = None
    for host, use_crumb in attempts:
        url = base.format(host=host)
        if use_crumb:
            crumb = yahoo_crumb()
            if crumb:
                url += "&crumb=" + urllib.parse.quote(crumb)
        try:
            data = json.loads(get(url))
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            return {
                "meta": {k: result["meta"][k] for k in META_KEYS if k in result.get("meta", {})},
                "timestamp": result["timestamp"],
                "indicators": {"quote": [{"close": [None if c is None else round(c, 4) for c in closes]}]},
            }
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            time.sleep(1.5)
        except Exception as e:
            last = f"{type(e).__name__}: {e}"[:150]
            time.sleep(1.5)
    raise RuntimeError(last or "no data")


def google_news(query, pattern):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": query, "hl": "nl", "gl": "NL", "ceid": "NL:nl"})
    root = ET.fromstring(get(url))
    cutoff = time.time() - NEWS_MAX_AGE_DAYS * 86400
    seen, items = set(), []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        source = (it.findtext("source") or "").strip()
        if source and title.endswith(" - " + source):
            title = title[: -(len(source) + 3)]
        try:
            ts = email.utils.parsedate_to_datetime(it.findtext("pubDate") or "").timestamp()
        except Exception:
            continue
        link = (it.findtext("link") or "").strip()
        key = title.lower()
        if not title or not pattern.search(title) or key in seen or ts < cutoff:
            continue
        seen.add(key)
        items.append({"title": title, "source": source, "time": int(ts * 1000),
                      "link": link if link.startswith("https://") else None})
    items.sort(key=lambda n: n["time"], reverse=True)
    return items[:8]


def main():
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    data.setdefault("charts", {})
    data.setdefault("news", {})
    data["errors"], data["newsErrors"] = {}, {}

    got_prices = False
    for key, symbol in SYMBOLS.items():
        try:
            data["charts"][key] = yahoo_chart(symbol)
            got_prices = True
        except Exception as e:
            data["errors"][key] = f"Yahoo Finance failed at {now}: {e}"
            print(f"{symbol}: {e}", file=sys.stderr)
        time.sleep(1)

    got_news = False
    for key, (query, pattern) in NEWS.items():
        try:
            data["news"][key] = google_news(query, pattern)
            got_news = True
        except Exception as e:
            data["newsErrors"][key] = f"Google News failed at {now}: {type(e).__name__}"
            print(f"news {key}: {e}", file=sys.stderr)

    if got_prices:
        data["updated"] = now
    if got_news:
        data["newsUpdated"] = now
    data["checked"] = now

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Prices {'ok' if got_prices else 'FAILED'}, news {'ok' if got_news else 'FAILED'}")


if __name__ == "__main__":
    main()
