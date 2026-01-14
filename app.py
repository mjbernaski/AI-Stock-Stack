import json
import yfinance as yf
from flask import Flask, jsonify, render_template
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import threading
import os

app = Flask(__name__)
CORS(app)

with open('config.json', 'r') as f:
    config = json.load(f)

HISTORY_FILE = 'historical_data.json'
LAYER_RATIO_CACHE_FILE = 'layer_ratio_history.json'

stock_data = {}
index_data = {}
historical_data = []
layer_ratio_history = []
lock = threading.Lock()

def load_historical_data():
    global historical_data
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                historical_data = json.load(f)
            print(f"Loaded {len(historical_data)} historical data points")
        except Exception as e:
            print(f"Error loading historical data: {e}")
            historical_data = []
    else:
        historical_data = []

def save_historical_data():
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(historical_data, f, indent=2)
    except Exception as e:
        print(f"Error saving historical data: {e}")

def load_layer_ratio_cache():
    if os.path.exists(LAYER_RATIO_CACHE_FILE):
        try:
            with open(LAYER_RATIO_CACHE_FILE, 'r') as f:
                cached_data = json.load(f)
            print(f"Loaded {len(cached_data)} cached layer ratio data points")
            return cached_data
        except Exception as e:
            print(f"Error loading layer ratio cache: {e}")
            return []
    else:
        return []

def save_layer_ratio_cache():
    try:
        with open(LAYER_RATIO_CACHE_FILE, 'w') as f:
            json.dump(layer_ratio_history, f, indent=2)
        print(f"Saved {len(layer_ratio_history)} layer ratio data points to cache")
    except Exception as e:
        print(f"Error saving layer ratio cache: {e}")

def format_market_cap(value):
    if value >= 1e12:
        return f"${value/1e12:.1f}T"
    elif value >= 1e9:
        return f"${value/1e9:.0f}B"
    elif value >= 1e6:
        return f"${value/1e6:.0f}M"
    return f"${value:.0f}"

def fetch_stock_data():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching stock data...")
    new_data = {}

    for layer_name, stocks in config['stocks'].items():
        new_data[layer_name] = []

        for stock_info in stocks:
            ticker = stock_info['ticker']
            try:
                stock = yf.Ticker(ticker)
                hist = stock.history(period='5d')

                if len(hist) < 2:
                    raise Exception("Insufficient historical data")

                current_price = float(hist['Close'].iloc[-1])
                prev_close = float(hist['Close'].iloc[-2])

                price_change = current_price - prev_close
                price_change_percent = (price_change / prev_close) * 100

                info = stock.info
                market_cap = info.get('marketCap')

                stock_entry = {
                    'ticker': ticker,
                    'name': stock_info['name'],
                    'price': current_price,
                    'marketCap': market_cap,
                    'marketCapFormatted': format_market_cap(market_cap) if market_cap else 'N/A',
                    'priceChange': float(price_change),
                    'priceChangePercent': float(price_change_percent),
                    'direction': 'up' if price_change > 0 else 'down' if price_change < 0 else 'neutral',
                    'lastUpdated': datetime.now().isoformat()
                }

                new_data[layer_name].append(stock_entry)
                print(f"  {ticker}: ${current_price:.2f} ({price_change_percent:+.2f}%)")

            except Exception as e:
                print(f"  Error fetching {ticker}: {str(e)}")
                new_data[layer_name].append({
                    'ticker': ticker,
                    'name': stock_info['name'],
                    'price': None,
                    'marketCap': None,
                    'marketCapFormatted': 'N/A',
                    'priceChange': 0,
                    'priceChangePercent': 0,
                    'direction': 'neutral',
                    'error': str(e)
                })

    total_market_cap = 0
    weighted_return = 0
    all_stocks = []
    layer_metrics = {}

    for layer_name, stocks in new_data.items():
        layer_total_mc = 0
        layer_weighted_return = 0
        layer_stock_count = 0

        for stock in stocks:
            if stock.get('marketCap') and stock.get('priceChangePercent') is not None:
                all_stocks.append(stock)
                total_market_cap += stock['marketCap']
                weighted_return += stock['marketCap'] * stock['priceChangePercent']

                layer_total_mc += stock['marketCap']
                layer_weighted_return += stock['marketCap'] * stock['priceChangePercent']
                layer_stock_count += 1

        if layer_total_mc > 0:
            layer_change_percent = layer_weighted_return / layer_total_mc
            layer_metrics[layer_name] = {
                'totalMarketCap': layer_total_mc,
                'totalMarketCapFormatted': format_market_cap(layer_total_mc),
                'changePercent': float(layer_change_percent),
                'direction': 'up' if layer_change_percent > 0 else 'down' if layer_change_percent < 0 else 'neutral',
                'stockCount': layer_stock_count
            }
        else:
            layer_metrics[layer_name] = {
                'totalMarketCap': 0,
                'totalMarketCapFormatted': 'N/A',
                'changePercent': 0,
                'direction': 'neutral',
                'stockCount': 0
            }

    if total_market_cap > 0:
        index_change_percent = weighted_return / total_market_cap
        new_index = {
            'totalMarketCap': total_market_cap,
            'totalMarketCapFormatted': format_market_cap(total_market_cap),
            'changePercent': float(index_change_percent),
            'direction': 'up' if index_change_percent > 0 else 'down' if index_change_percent < 0 else 'neutral',
            'stockCount': len(all_stocks),
            'lastUpdated': datetime.now().isoformat(),
            'layers': layer_metrics
        }
        print(f"  Tech Stack Index: {index_change_percent:+.2f}% (Total Market Cap: {format_market_cap(total_market_cap)})")
    else:
        new_index = {
            'totalMarketCap': 0,
            'totalMarketCapFormatted': 'N/A',
            'changePercent': 0,
            'direction': 'neutral',
            'stockCount': 0,
            'lastUpdated': datetime.now().isoformat(),
            'layers': layer_metrics
        }

    with lock:
        stock_data.clear()
        stock_data.update(new_data)
        index_data.clear()
        index_data.update(new_index)

        historical_entry = {
            'timestamp': datetime.now().isoformat(),
            'index': new_index.copy(),
            'stocks': {}
        }

        for layer_name, stocks in new_data.items():
            for stock in stocks:
                ticker = stock['ticker']
                historical_entry['stocks'][ticker] = {
                    'price': stock.get('price'),
                    'marketCap': stock.get('marketCap'),
                    'priceChangePercent': stock.get('priceChangePercent'),
                    'direction': stock.get('direction')
                }

        historical_data.append(historical_entry)

        max_history_points = 500
        if len(historical_data) > max_history_points:
            historical_data.pop(0)

        save_historical_data()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Stock data updated successfully")

def fetch_historical_layer_ratios():
    global layer_ratio_history
    from datetime import timedelta

    cached_data = load_layer_ratio_cache()

    end_date = datetime.now()

    if cached_data and len(cached_data) > 0:
        last_cached_date_str = cached_data[-1]['date']
        last_cached_date = datetime.strptime(last_cached_date_str, '%Y-%m-%d')
        start_date = last_cached_date + timedelta(days=1)

        if start_date.date() >= end_date.date():
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Layer ratio cache is up to date ({len(cached_data)} data points)")
            with lock:
                layer_ratio_history = cached_data
            return cached_data

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Updating layer ratios from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}...")
    else:
        start_date = end_date - timedelta(days=365)
        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fetching 12-month historical data for layer ratios...")
        print(f"  Fetching historical data from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}...")

    all_tickers = []
    ticker_to_layer = {}

    for layer_name, stocks in config['stocks'].items():
        for stock_info in stocks:
            ticker = stock_info['ticker']
            all_tickers.append(ticker)
            ticker_to_layer[ticker] = layer_name

    daily_layer_market_caps = {}

    for ticker in all_tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(start=start_date, end=end_date, interval='1d')

            if len(hist) == 0:
                print(f"  Warning: No historical data for {ticker}")
                continue

            info = stock.info
            current_market_cap = info.get('marketCap')

            if not current_market_cap:
                print(f"  Warning: No market cap data for {ticker}")
                continue

            current_price = float(hist['Close'].iloc[-1])

            for date_idx in hist.index:
                date_str = date_idx.strftime('%Y-%m-%d')
                price_on_date = float(hist.loc[date_idx, 'Close'])

                market_cap_on_date = current_market_cap * (price_on_date / current_price)

                if date_str not in daily_layer_market_caps:
                    daily_layer_market_caps[date_str] = {
                        'layer1': 0, 'layer2': 0, 'layer3': 0, 'layer4': 0
                    }

                layer = ticker_to_layer[ticker]
                daily_layer_market_caps[date_str][layer] += market_cap_on_date

            print(f"  {ticker}: {len(hist)} days of data")

        except Exception as e:
            print(f"  Error fetching historical data for {ticker}: {str(e)}")

    new_ratio_data = []

    for date_str in sorted(daily_layer_market_caps.keys()):
        layer_caps = daily_layer_market_caps[date_str]

        if layer_caps['layer1'] == 0 or layer_caps['layer2'] == 0 or layer_caps['layer3'] == 0 or layer_caps['layer4'] == 0:
            continue

        foundation_cap = layer_caps['layer1']
        total_market_cap = layer_caps['layer1'] + layer_caps['layer2'] + layer_caps['layer3'] + layer_caps['layer4']

        if foundation_cap > 0:
            ratios = {
                'date': date_str,
                'totalMarketCap': total_market_cap,
                'layer1': 1.0,
                'layer2': layer_caps['layer2'] / foundation_cap,
                'layer3': layer_caps['layer3'] / foundation_cap,
                'layer4': layer_caps['layer4'] / foundation_cap
            }
            new_ratio_data.append(ratios)

    combined_data = cached_data + new_ratio_data

    with lock:
        layer_ratio_history = combined_data

    save_layer_ratio_cache()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Layer ratios updated: {len(combined_data)} total data points ({len(new_ratio_data)} new)")
    return combined_data

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/stocks')
def get_stocks():
    with lock:
        return jsonify({
            'stocks': stock_data,
            'index': index_data
        })

@app.route('/api/config')
def get_config():
    return jsonify({
        'updateInterval': config['scheduler']['update_interval_minutes']
    })

@app.route('/api/history')
def get_history():
    with lock:
        return jsonify(historical_data)

@app.route('/api/layer-ratios')
def get_layer_ratios():
    with lock:
        return jsonify(layer_ratio_history)

if __name__ == '__main__':
    load_historical_data()
    fetch_stock_data()
    fetch_historical_layer_ratios()

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=fetch_stock_data,
        trigger="interval",
        minutes=config['scheduler']['update_interval_minutes']
    )
    scheduler.start()

    try:
        app.run(
            host=config['server']['host'],
            port=config['server']['port'],
            debug=True,
            use_reloader=False
        )
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()
