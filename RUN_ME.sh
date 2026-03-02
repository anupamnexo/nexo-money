#!/bin/bash
# ============================================
# Nexo.money MVP — Quick Start
# ============================================
# Requirements: Python 3.8+ and pip
#
# This script installs tornado (the only dependency),
# seeds the database with demo data, and starts the server.
# ============================================

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║       🚀 Nexo.money MVP             ║"
echo "  ║  Corporate Cards for Indian SMEs     ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# Navigate to script directory
cd "$(dirname "$0")"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3.8+ first."
    exit 1
fi

echo "📦 Installing tornado (only dependency)..."
pip3 install tornado --quiet 2>/dev/null || pip install tornado --quiet 2>/dev/null

echo "🗄️  Initializing database with demo data..."
rm -f nexo.db

echo "🚀 Starting Nexo.money server..."
echo ""
echo "  📄 Landing Page:  http://localhost:8080"
echo "  📊 Dashboard App: http://localhost:8080/app"
echo ""
echo "  Demo Login:"
echo "    Email:    priya.shah@technova.com"
echo "    Password: demo123"
echo ""
echo "  Press Ctrl+C to stop the server"
echo "  ─────────────────────────────────────────"
echo ""

python3 app.py --seed
