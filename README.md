# ÜSTAT - VİOP Algorithmic Trading System

Automated trading system for VİOP (Borsa Istanbul Derivatives Market) built with Python engine, FastAPI backend, and Electron + React desktop application.

## Architecture

- **engine/** - Python trading engine (10-second cycle)
- **api/** - FastAPI backend bridge
- **desktop/** - Electron + React desktop UI
- **backtest/** - Backtesting framework
- **tests/** - Test suite

## Setup

```bash
pip install -r requirements.txt
cd desktop && npm install
```

## Run

```bash
# Start engine
python engine/main.py

# Start API
uvicorn api.server:app --port 8000

# Start desktop
cd desktop && npm start
```
