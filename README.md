# [Project Title] - S&P Global & CRISIL Campus Hackathon

**Candidate Name:** [Candidate Name]
**College Email ID:** [College Email]
**College / Campus:** [Campus]
**Demo Video Link:** [YouTube Unlisted Demo Link]
**Slide Deck Link:** [Presentation Link]

## 1. Project Overview & Problem Statement
This project is a working risk-intelligence prototype designed to ingest financial news, semantically deduplicate events, and dynamically rebalance a stock index based on real-time and offline macroeconomic stress scenarios. 

The core problem addressed is the rapid incorporation of unstructured market events (news headlines) into actionable portfolio weighting decisions without relying exclusively on lagging market price data. The system demonstrates an event-driven tactical rebalancer (Module A) and a macroeconomic stress testing engine (Module B).

## 2. Approach & System Architecture
The application pipeline operates through the following stages:
1. **Ingestion:** Fetches live headlines via Google News RSS or loads synthetic data in offline "Crisis Replay" mode.
2. **Entity Resolution & Semantic Deduplication:** Normalizes ticker symbols and prevents identical event duplication via a local SQLite database using article hashes.
3. **Risk Engine:** Computes sentiment, impact, and confidence scores. Operates in a hybrid mode: an optional LLM path via Groq, or a fully offline fallback using a local TF-IDF + Logistic Regression NLP model.
4. **Module A (Tactical Index Rebalancer):** Uses risk signals alongside deterministic reference prices to dynamically shift asset weights via simplex projection.
5. **Module B (Stress Engine):** Performs predefined cross-asset sensitivity and contagion risk analysis based on historical/synthetic beta and correlation matrices.
6. **Visualization:** A Streamlit dashboard presents the execution ticket, risk radar, and strategic stress scenarios.

### Technology Stack
- **Languages/Core:** Python 3, SQLite (standard library), XML/RSS (standard library)
- **Data & ML:** pandas, NumPy, scikit-learn
- **Dashboard & Visualization:** Streamlit, Plotly
- **External APIs:** Groq (Optional), python-dotenv

## 3. Dataset Used & Provenance

### `data/all-data.csv` (4,845 rows)
- **Nature:** Unstructured text with sentiment labels (sentiment, sentence).
- **Purpose:** Used strictly to train the offline TF-IDF + Logistic Regression fallback NLP model.
- **Source:** The repository currently does not preserve authoritative provenance metadata for this file. The file is bundled locally and is used only for training the offline fallback NLP model. Its structure resembles the FinancialPhraseBank dataset, but this repository does not claim that provenance without verification.

### `data/sample_news.json` (5 records)
- **Nature:** Synthetic/mock replay data.
- **Purpose:** Enables deterministic/offline demonstration of the ingestion and risk engine pipeline.
- **Source:** Explicitly labeled internally as "Replay-Feed".

### `data/reference_prices.json` (10 tickers)
- **Nature:** Deterministic synthetic reference prices as-of 2024-01-01.
- **Purpose:** Assumes a flat $100 baseline value across 10 portfolio tickers to ensure deterministic offline execution for the rebalancer logic. 
- **Assumptions:** These are synthetic baseline values used for algorithmic testing and do not represent live market prices.

### `data/risk_data.db`
- **Nature:** Local runtime SQLite database.
- **Purpose:** Used for semantic deduplication and audit tracking of processed signals, not a source dataset.

## 4. Quickstart & Installation

**Runtime & OS:** Python 3 (tested on Linux).

```bash
# 1. Clone the repository
git clone <repository-url>
cd <repository-directory>

# 2. Create and activate a virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Optional: Configure Groq API Key
# Create a .env file and add your key to enable deep LLM extraction.
# The key is loaded server-side and never entered in the UI.
echo "GROQ_API_KEY=your_key_here" > .env

# 5. Run the application
streamlit run src/dashboard/app.py
```
*Note: The application can run fully offline in "Offline Crisis Replay" mode if external news or the Groq API are unavailable.*

## 5. Results & Testing
- **Testing:** The system includes a comprehensive `pytest` suite ensuring correct functioning of semantic deduplication, risk analysis, and mathematical rebalancing. Currently, 48/48 tests pass successfully.
- **Functionality:** The dashboard dynamically allocates capital in response to injected news events and properly handles offline operations without relying on live financial APIs.
- **Performance:** As a prototype, results are qualitative. The system demonstrates immediate algorithmic adjustment to unstructured text inputs and strict deduplication.

## 6. Domain Impact
By decoupling portfolio rebalancing from traditional price-lagged indicators and directly integrating unstructured NLP, this prototype demonstrates a reactive, event-driven risk mitigation strategy suitable for tactical asset allocation and algorithmic stress testing.

## 7. Repository Structure
```
.
├── README.md               # Project documentation
├── LICENSE                 # Standard MIT License
├── requirements.txt        # Python dependency declarations
├── docs/                   # Presentation and architecture diagrams
├── data/
│   ├── all-data.csv            # NLP training data
│   ├── sample_news.json        # Offline replay mock data
│   ├── reference_prices.json   # Deterministic reference prices
│   └── risk_data.db            # Local runtime SQLite database
├── src/
│   ├── dashboard/          # Streamlit UI
│   ├── engine/             # NLP Risk Engine, Stress Engine, Ingestion
│   ├── rebalancer/         # Module A Index Rebalancer logic
│   └── storage/            # SQLite database interface
└── tests/                  # Pytest test suite
```

## 8. Current Limitations & Reproducibility
- **Dataset Provenance:** The origin and licensing for `data/all-data.csv` is not established definitively within the repository.
- **Deterministic Prices:** Reference prices are synthetic $100 values rather than live market data, ensuring reproducibility at the cost of real-world precision.
- **Predefined Stress Models:** Macroeconomic stress assumptions and contagion risks are based on predefined historical correlation matrices rather than live calculations.
- **Prototype Scope:** Groq API access is optional but enhances extraction precision. This is a hackathon prototype, not a production-grade investment advisory system.

### Prototype Caveat: Banking Book Synthetic Credit Stress
Module B contains two conceptually separate books:
- **Trading Book market stress:** Stresses the equity portfolio dynamically based on market shocks.
- **Banking Book synthetic credit stress:** Applies credit multipliers to a separate, offline synthetic loan portfolio.
The credit portfolio is purely **synthetic**. All PD, LGD, EAD, and risk-weight values are illustrative assumptions for prototype demonstration. Scenario multipliers (e.g., PD multipliers) are also strictly synthetic assumptions. The "CET1 Capital Burden" is a simplified mathematical metric (Stressed ECL / Initial Synthetic CET1 Capital) designed to conceptually demonstrate capital impact; it is **NOT** a Basel-compliant CET1 ratio.
