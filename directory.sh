#!/bin/bash

set -e

BASE_DIR="tradepilot"

# Create directories
mkdir -p $BASE_DIR/{data,signals,strategy,risk,execution,memory,utils}

# Create main files
touch $BASE_DIR/main.py
touch $BASE_DIR/config.yaml

# data
touch $BASE_DIR/data/fetcher.py
touch $BASE_DIR/data/universe.py

# signals
touch $BASE_DIR/signals/indicators.py
touch $BASE_DIR/signals/regime.py
touch $BASE_DIR/signals/scorer.py

# strategy
touch $BASE_DIR/strategy/mean_reversion.py
touch $BASE_DIR/strategy/simulator.py

# risk
touch $BASE_DIR/risk/sizer.py
touch $BASE_DIR/risk/monitor.py

# execution
touch $BASE_DIR/execution/router.py
touch $BASE_DIR/execution/broker.py

# memory
touch $BASE_DIR/memory/context.py

# utils
touch $BASE_DIR/utils/logger.py
touch $BASE_DIR/utils/display.py

echo "✅ tradepilot project structure created successfully."