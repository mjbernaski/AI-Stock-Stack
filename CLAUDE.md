# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AI-Stock-Stack is a technology stock market analysis application that visualizes companies organized by market cap layers:
- Layer 1: Foundation (semiconductor/materials companies like TSMC, Micron)
- Layer 2: Compute & Logic (chip designers like Nvidia, AMD, Qualcomm)
- Layer 3: Cloud & Data (cloud providers like Microsoft, Google, Amazon)
- Layer 4: Interface & App (consumer-facing tech like Apple, Meta, Tesla)

## Architecture

The application follows a layered architecture pattern that mirrors the technology stack layers being analyzed. When implementing features:

- **Data Layer**: Handle stock market data fetching, caching, and processing for the companies across all four technology layers
- **Analysis Layer**: Implement market cap calculations, trend analysis, and layer-specific insights
- **Visualization Layer**: Render the layered market cap UI as shown in UI_Design.png
- **API Integration**: Connect to stock market data APIs for real-time pricing and company information

## Development Setup

When setting up the project for the first time:

1. Use a Python virtual environment for backend services:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On macOS/Linux
   ```

2. Store API endpoints and service URLs in a JSON configuration file (not hardcoded) to allow easy modification

## Key Considerations

- The UI should display companies organized into four distinct colored layers matching the design
- Each company card shows: ticker symbol, company name, and market cap
- Market cap data should be fetched from reliable financial APIs
- Consider caching strategies for stock data to avoid excessive API calls
- The layered visualization should clearly show the technology value chain hierarchy
