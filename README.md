# AI Stock Stack

Real-time technology stock market visualization showing companies organized by their market cap layers in the tech value chain.

## Features

- Live stock price tracking for 22 major technology companies
- Automatic updates every 15 minutes
- Four-layer visualization:
  - Layer 1: Foundation (semiconductors/materials)
  - Layer 2: Compute & Logic (chip designers)
  - Layer 3: Cloud & Data (cloud providers)
  - Layer 4: Interface & App (consumer tech)
- Real-time price change indicators with directional arrows
- Market cap display for each company

## Setup

1. Activate the virtual environment:
```bash
source venv/bin/activate
```

2. Run the application:
```bash
python app.py
```

3. Open your browser to: http://localhost:5000

## Configuration

Edit `config.json` to:
- Change the update interval (default: 15 minutes)
- Modify server host/port
- Add or remove stock tickers from any layer

## Architecture

- **Backend**: Flask web server with yfinance for stock data
- **Scheduler**: APScheduler for periodic price updates
- **Frontend**: Vanilla JavaScript with real-time updates
- **Data Source**: Yahoo Finance via yfinance library
