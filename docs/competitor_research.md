# Competitor Research Report

## 1. Accessible and Inspected Repositories

The following 14 repositories were successfully cloned and inspected:
- **VIT-Bhopal-Abhi-Pandey-S-P-Crisil-hackathon**
- **VIT_Bhopal-Anubhav_Jha-Hackathon**
- **VIT_Bhopal_University-Pulkit_Agrawal-Hackathon_**
- **vit-mehwish-hackathon**
- **DelhiTechnologicalUniversity-NishantAgarwal-Hackathon**
- **igdtuw-bhavya-hackathon**
- **IGDTUW-Chaitenya-Chand-Hackathon**
- **IIITD-Vansh-Goyal-hackathon**
- **iiitranchi-medhansh-poojari-hackathon**
- **iit-kharagpur-aman-gupta-hackathon**
- **IITKharagpur-Shubham-Suman-hackathon**
- **iitpatna-katariya-hemanth-kumar-hackathon**
- **mit-manipal-dhruv-thacker-hackathon**
- **mit-manipal-harsh-upadhyay-hackathon**

None of the provided repositories failed to clone; all were accessible and analyzed.

## 2. Evidence-Backed Comparison Matrix

| Competitor Repository | Architecture & Separation | Ingestion & Entity Resolution | NLP & Sentiment | Portfolio & Stress Testing | Frontend & Visualization |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **VIT-Bhopal (Abhi Pandey)** | Full-stack (React/FastAPI) | Basic entity mapping | FinBERT sentiment, custom impact | Basic stress tests with predefined scenarios | Interactive charts, terminal-like UI for live analysis |
| **VIT_Bhopal (Pulkit Agrawal)** | Backend API + React App | Clear separation of textual ingestion, credibility | Multi-factor NLP, risk taxonomy mapping | Synthetic portfolio math, risk magnitude | High clarity, component-based event detail pages |
| **IIT Kharagpur (Aman Gupta)** | React + Python (pyproject) | NLP data extraction pipelines | Transformer-based models | Statistical stress testing | NextJS/React layout, clean charts |
| **VIT (Mehwish)** | Python Monolith + Streamlit | Basic ingestion from financial sources | Core sentiment extraction | Dynamic rebalancer & event-driven stress | Streamlit dashboard (lower interactivity) |
| **IIT Patna (Katariya H. Kumar)**| FastAPI + Streamlit | Python modules for entity | Modular pipeline for event classification | Portfolio allocation via rebalancer | Streamlit based standard charts |
| **DTU (Nishant Agarwal)** | Client/Server (Node/Python) | Structured JSON processing | Basic string mapping / NLTK | Simple weighted portfolio | Static React/Vue interface |
| **Others (Various)** | Mostly Backend-heavy scripts | Command-line scripts / static JSON data | HuggingFace wrappers | Basic VaR and Monte Carlo formulas | Simple CLI or static HTML tables |

## 3. Best Reusable Ideas

- **Terminal-style Live Analysis View**: Using an interactive terminal component to simulate real-time news ingestion and risk evaluation (as seen in Abhi Pandey's UI). It gives a strong "live feed" impression.
- **Corroboration and Novelty Scoring**: Fusing multiple data sources and adding weights based on whether news is corroborated by trusted sources (Pulkit Agrawal's methodology).
- **Synthetic Portfolio Scenarios**: Using predefined financial shock scenarios (e.g., inflation surge, supply chain breakdown) to demonstrate stress testing without needing real bank API integration.
- **Microservice / Modular NLP Pipeline**: Decoupling the "event classification" from "sentiment analysis" into separate configurable steps so you can swap out models easily.

## 4. Ideas Deliberately Rejected and Why

- **Rewriting in React + FastAPI**: While some competitors used React, we explicitly rejected rewriting our application to preserve stability and meet the Phase 8/13 rules (no architecture rewrites). We retained our Streamlit frontend to ensure a reliable demo.
- **Heavy Monte Carlo Simulations**: Running full 10,000-path Monte Carlo simulations on the backend causes UI blocking and extreme latency. We will use simplified VaR (Value at Risk) or deterministic shock formulas for instant demo responsiveness.
- **Live Social Media Crawling in Production**: Attempting to scrape Reddit or X in real-time proved fragile in competitor repos due to rate limits. We will instead mock the live feed ingestion or use a static, curated dataset to guarantee the demo works perfectly.

## 5. Recommended Changes for Our Project (Ordered by Impact & Risk)

1. **Implement Scenario-Based Stress Testing** (Impact: High, Risk: Medium)
   - Do not just calculate a single risk number. Provide an interface where the user can click "Supply Chain Crisis" or "Tech Stock Crash" and see the portfolio instantly adjust.

2. **Terminal-style Live Analysis View in Streamlit** (Impact: High, Risk: Low)
   - Enhance the Streamlit UI with terminal-like text outputs to simulate real-time news ingestion and risk evaluation.

3. **Enhance Entity Resolution and Taxonomy Mapping** (Impact: Medium, Risk: Medium)
   - Map events to a specific taxonomy (e.g., "Interest Rates", "Geopolitical", "M&A") so we can demonstrate sector-specific risk allocation.

4. **Add a Live Feed / Demo Mode** (Impact: High, Risk: Low)
   - Use the deterministic offline replay data as the default demo mode to showcase the engine reacting to events, preventing the "empty state" problem often seen in hackathons.
