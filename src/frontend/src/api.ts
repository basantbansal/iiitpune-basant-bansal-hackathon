const API_BASE = "/api";

export const api = {
  getHealth: () => fetch(`${API_BASE}/health`, { cache: "no-store" }).then(r => r.json()),
  getHealthDetails: () => fetch(`${API_BASE}/health?details=true`, { cache: "no-store" }).then(r => r.json()),
  
  getConfig: () => fetch(`${API_BASE}/config`, { cache: "no-store" }).then(r => r.json()),
  
  getPortfolio: () => fetch(`${API_BASE}/portfolio`, { cache: "no-store" }).then(r => r.json()),
  
  getPortfolioMetrics: () => fetch(`${API_BASE}/portfolio/metrics`, { cache: "no-store" }).then(r => r.json()),
  
  getStocks: () => fetch(`${API_BASE}/stocks`, { cache: "no-store" }).then(r => r.json()),
  
  getStockDetails: (ticker: string) => fetch(`${API_BASE}/stocks/${ticker}/details`, { cache: "no-store" }).then(r => r.json()),
  
  getStockHistory: (ticker: string, period: string = "1Y") => fetch(`${API_BASE}/stocks/${ticker}/history?period=${period}`, { cache: "no-store" }).then(r => r.json()),
  
  getRiskSignals: () => fetch(`${API_BASE}/risk-signals`, { cache: "no-store" }).then(r => r.json()),
  
  scanMarket: () => fetch(`${API_BASE}/market-scan`, { method: "POST", cache: "no-store" }).then(r => r.json()),
  
  getStressScenarios: () => fetch(`${API_BASE}/stress-scenarios`, { cache: "no-store" }).then(r => r.json()),
  
  runStressTest: (scenario_name: string) => fetch(`${API_BASE}/stress-test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_name }),
    cache: "no-store"
  }).then(r => r.json()),

  getPortfolioHistory: () => fetch(`${API_BASE}/portfolio/history`, { cache: "no-store" }).then(r => r.json()),

  getStressTrigger: () => fetch(`${API_BASE}/stress-trigger`, { cache: "no-store" }).then(r => r.json()),
  
  updateConfig: (config: any) => fetch(`${API_BASE}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
    cache: "no-store"
  }).then(r => r.json()),
  
  resetData: () => fetch(`${API_BASE}/reset`, { method: "POST", cache: "no-store" }).then(r => r.json()),

  updateHoldings: (holdings: Record<string, number>) => fetch(`${API_BASE}/portfolio/holdings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ holdings }),
    cache: "no-store"
  }).then(async r => {
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: "Failed to update holdings" }));
      throw new Error(err.detail || "Failed to update holdings");
    }
    return r.json();
  }),

  resetHoldings: () => fetch(`${API_BASE}/portfolio/reset-holdings`, {
    method: "POST",
    cache: "no-store"
  }).then(r => r.json()),
};
