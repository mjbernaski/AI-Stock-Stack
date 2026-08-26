"""Tavily-backed news fetching for the tracked stocks.

Mirrors the pattern used for stock data in app.py: an in-memory store guarded by
a lock, backed by a JSON file cache on disk so headlines survive a restart.
"""

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse

import requests

NEWS_CACHE_FILE = 'news_cache.json'
TAVILY_ENDPOINT = 'https://api.tavily.com/search'
MAX_WORKERS = 4
REQUEST_TIMEOUT = 20

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
        with open(NEWS_CACHE_FILE, 'w') as f:
            json.dump({'meta': news_meta, 'news': news_data}, f, indent=2)
    except Exception as e:
        print(f"Error saving news cache: {e}")

def source_from_url(url):
    try:
        host = urlparse(url).netloc
        return host[4:] if host.startswith('www.') else host
    except Exception:
        return ''

def fetch_news_for_ticker(ticker, name, settings, api_key):
    """Return (ticker, entry). Never raises; failures come back on the entry."""
    query = f"{name} ({ticker}) stock news"
    payload = {
        'query': query,
        'topic': 'news',
        'days': settings['days'],
        'max_results': settings['max_results'],
        'search_depth': settings['search_depth'],
    }

    entry = {
        'ticker': ticker,
        'name': name,
        'fetchedAt': datetime.now().isoformat(),
        'articles': [],
    }

    try:
        response = requests.post(
            TAVILY_ENDPOINT,
            json=payload,
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            detail = response.json().get('detail', response.text)
            if isinstance(detail, dict):
                detail = detail.get('error', detail)
            raise Exception(f"HTTP {response.status_code}: {detail}")

        for result in response.json().get('results', []):
            url = result.get('url', '')
            entry['articles'].append({
                'title': result.get('title', ''),
                'url': url,
                'source': source_from_url(url),
                'publishedDate': result.get('published_date'),
                'snippet': (result.get('content') or '')[:280],
                'score': result.get('score'),
            })

        print(f"  {ticker}: {len(entry['articles'])} stories")

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
