"""Tavily-backed news fetching for the tracked stocks.

Mirrors the pattern used for stock data in app.py: an in-memory store guarded by
a lock, backed by a JSON file cache on disk so headlines survive a restart.
"""

import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

import requests

from storage import write_json_atomic

NEWS_CACHE_FILE = 'news_cache.json'
TAVILY_ENDPOINT = 'https://api.tavily.com/search'
MAX_WORKERS = 4
REQUEST_TIMEOUT = 20

# Tavily bills per search, not per result, so we over-fetch and then discard
# stories that never actually mention the company. Without this, generic market
# wraps and 13F-filing spam crowd out real coverage.
OVERFETCH_MULTIPLIER = 3
MAX_OVERFETCH = 12
SNIPPET_LENGTH = 280

# Quote pages, screeners and listing pages that Tavily's news index returns
# alongside real reporting. They name the company but carry no story.
NON_NEWS_TITLE = re.compile(
    r'stock price today|quote & chart|quote, market cap|share price|'
    r'latest stock news & headlines|stock price, quote|price today \(|'
    r'live quote|stock option|– quote|\bquotes?\b.*\bchart\b',
    re.IGNORECASE,
)

# Words too common across these company names to identify a story on their own.
GENERIC_NAME_TOKENS = {
    'inc', 'corp', 'corporation', 'holdings', 'company', 'group', 'international',
    'technology', 'technologies', 'systems', 'networks', 'materials', 'research',
    'services', 'energy', 'computer', 'micro', 'ltd', 'plc',
}

news_data = {}
news_meta = {}
lock = threading.Lock()

def get_api_key():
    return os.environ.get('TAVILY_API_KEY')

def load_news_cache():
    global news_data, news_meta
    if not os.path.exists(NEWS_CACHE_FILE):
        news_data = {}
        news_meta = {}
        return

    try:
        with open(NEWS_CACHE_FILE, 'r') as f:
            cached = json.load(f)
        news_data = cached.get('news', {})
        news_meta = cached.get('meta', {})
        print(f"Loaded cached news for {len(news_data)} tickers")
    except Exception as e:
        print(f"Error loading news cache: {e}")
        news_data = {}
        news_meta = {}

def save_news_cache():
    try:
        write_json_atomic(NEWS_CACHE_FILE, {'meta': news_meta, 'news': news_data})
    except Exception as e:
        print(f"Error saving news cache: {e}")

def source_from_url(url):
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith('www.') else host
    except Exception:
        return ''

def relevance_patterns(ticker, name):
    """Patterns that indicate a story is actually about this company.

    The ticker is matched case-sensitively so tickers that are ordinary words
    (NOW, ARM) don't match prose; name tokens are matched case-insensitively.
    """
    patterns = [re.compile(rf'\b{re.escape(ticker)}\b')]
    for token in name.split():
        cleaned = token.strip('.,')
        if len(cleaned) >= 3 and cleaned.lower() not in GENERIC_NAME_TOKENS:
            patterns.append(re.compile(rf'\b{re.escape(cleaned)}\b', re.IGNORECASE))
    return patterns

def dedupe_key(title):
    """Collapse the same story syndicated across editions.

    Outlets re-run a wire story under a trimmed headline and a different
    suffix ("- Yahoo Finance" vs "- Yahoo! Finance Canada"), so compare a
    normalized prefix of the headline with the outlet suffix removed.
    """
    head = title.rsplit(' - ', 1)[0] if ' - ' in title else title
    return re.sub(r'[^a-z0-9]', '', head.lower())[:50]

def is_relevant(result, patterns):
    """Require the company to be the subject of the headline.

    Matching the body (or even the opening snippet) lets through institutional
    -holdings filings that list dozens of tickers, so a story about an unrelated
    company surfaces under half the portfolio. The headline is the subject test.
    """
    title = result.get('title', '')
    if not title or NON_NEWS_TITLE.search(title):
        return False
    return any(p.search(title) for p in patterns)

def search_tavily(query, days, wanted, settings, api_key):
    """One Tavily news search. Raises on a non-200 so the caller can record it."""
    response = requests.post(
        TAVILY_ENDPOINT,
        json={
            'query': query,
            'topic': 'news',
            'days': days,
            'max_results': min(wanted * OVERFETCH_MULTIPLIER, MAX_OVERFETCH),
            'search_depth': settings['search_depth'],
        },
        headers={'Authorization': f'Bearer {api_key}'},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code != 200:
        detail = response.json().get('detail', response.text)
        if isinstance(detail, dict):
            detail = detail.get('error', detail)
        raise Exception(f"HTTP {response.status_code}: {detail}")

    return response.json().get('results', [])

def fetch_news_for_ticker(ticker, name, settings, api_key):
    """Return (ticker, entry). Never raises; failures come back on the entry."""
    wanted = settings['max_results']
    query = f"{name} {ticker} stock"

    entry = {
        'ticker': ticker,
        'name': name,
        'fetchedAt': datetime.now().isoformat(),
        'articles': [],
    }

    try:
        patterns = relevance_patterns(ticker, name)
        min_score = settings.get('min_score', 0)
        days = settings['days']

        def keepers(results):
            seen = set()
            out = []
            for r in results:
                if not is_relevant(r, patterns) or (r.get('score') or 0) < min_score:
                    continue
                # Syndicated stories repeat across outlets under the same headline.
                key = dedupe_key(r.get('title') or '')
                if key in seen:
                    continue
                seen.add(key)
                out.append(r)
            return out

        results = search_tavily(query, days, wanted, settings, api_key)
        kept = keepers(results)

        # Thinly-covered names can have no on-topic story in the normal window;
        # widen it once rather than showing an empty card.
        fallback_days = settings.get('fallback_days')
        if not kept and fallback_days and fallback_days > days:
            results = search_tavily(query, fallback_days, wanted, settings, api_key)
            kept = keepers(results)
            if kept:
                entry['windowDays'] = fallback_days

        entry['discardedCount'] = len(results) - len(kept)

        for result in kept[:wanted]:
            url = result.get('url', '')
            entry['articles'].append({
                'title': result.get('title', ''),
                'url': url,
                'source': source_from_url(url),
                'publishedDate': result.get('published_date'),
                'snippet': (result.get('content') or '')[:SNIPPET_LENGTH],
                'score': result.get('score'),
            })

        print(f"  {ticker}: {len(entry['articles'])} stories "
              f"({entry['discardedCount']} off-topic discarded)")

    except Exception as e:
        entry['error'] = str(e)
        print(f"  Error fetching news for {ticker}: {e}")

    return ticker, entry

def fetch_all_news(config):
    """Refresh headlines for every configured ticker.

    A ticker that fails keeps whatever headlines it already had, so a bad API
    call degrades to stale news rather than an empty card.
    """
    settings = config.get('news', {})
    if not settings.get('enabled', True):
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] News fetching disabled, skipping")
        return

    api_key = get_api_key()
    if not api_key:
        print("TAVILY_API_KEY not set; skipping news fetch")
        with lock:
            news_meta['error'] = 'TAVILY_API_KEY not set'
        return

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching news...")

    targets = []
    for layer_name, stocks in config['stocks'].items():
        for stock_info in stocks:
            targets.append((layer_name, stock_info['ticker'], stock_info['name']))

    results = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [
            executor.submit(fetch_news_for_ticker, ticker, name, settings, api_key)
            for _, ticker, name in targets
        ]
        for future in futures:
            ticker, entry = future.result()
            results[ticker] = entry

    layer_by_ticker = {ticker: layer_name for layer_name, ticker, _ in targets}

    with lock:
        failures = 0
        for ticker, entry in results.items():
            entry['layer'] = layer_by_ticker[ticker]
            previous = news_data.get(ticker)
            if entry.get('error'):
                failures += 1
                if previous and previous.get('articles'):
                    # Keep the stale headlines, but record why they are stale.
                    previous['error'] = entry['error']
                    previous['staleSince'] = entry['fetchedAt']
                    continue
            news_data[ticker] = entry

        # Drop tickers that are no longer in config.json.
        for ticker in list(news_data):
            if ticker not in layer_by_ticker:
                del news_data[ticker]

        news_meta.clear()
        news_meta.update({
            'fetchedAt': datetime.now().isoformat(),
            'days': settings['days'],
            'maxResults': settings['max_results'],
            'tickerCount': len(results),
            'failureCount': failures,
        })

        save_news_cache()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] News updated: "
          f"{len(results) - failures}/{len(results)} tickers succeeded")

def get_news():
    with lock:
        return {'meta': dict(news_meta), 'news': json.loads(json.dumps(news_data))}

def get_news_for_ticker(ticker):
    with lock:
        entry = news_data.get(ticker.upper())
        return json.loads(json.dumps(entry)) if entry else None
