const API_BASE = "/api";

export const api = {
  getHealth: () => fetch(`${API_BASE}/health`).then(r => r.json()),
  getHealthDetails: () => fetch(`${API_BASE}/health?details=true`).then(r => r.json()),
  
  getConfig: () => fetch(`${API_BASE}/config`).then(r => r.json()),
  
  getPortfolio: () => fetch(`${API_BASE}/portfolio`).then(r => r.json()),
  
  getPortfolioMetrics: () => fetch(`${API_BASE}/portfolio/metrics`).then(r => r.json()),
  
  getStocks: () => fetch(`${API_BASE}/stocks`).then(r => r.json()),
  
  getStockDetails: (ticker: string) => fetch(`${API_BASE}/stocks/${ticker}/details`).then(r => r.json()),
  
  getStockHistory: (ticker: string, period: string = "1Y") => fetch(`${API_BASE}/stocks/${ticker}/history?period=${period}`).then(r => r.json()),
  
  getRiskSignals: () => fetch(`${API_BASE}/risk-signals`).then(r => r.json()),
  
  scanMarket: () => fetch(`${API_BASE}/market-scan`, { method: "POST" }).then(r => r.json()),
  
  getStressScenarios: () => fetch(`${API_BASE}/stress-scenarios`).then(r => r.json()),
  
  runStressTest: (scenario_name: string) => fetch(`${API_BASE}/stress-test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario_name })
  }).then(r => r.json()),

  getPortfolioHistory: () => fetch(`${API_BASE}/portfolio/history`).then(r => r.json()),

  getStressTrigger: () => fetch(`${API_BASE}/stress-trigger`).then(r => r.json()),
  
  updateConfig: (config: any) => fetch(`${API_BASE}/config`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config)
  }).then(r => r.json()),
  
  resetData: () => fetch(`${API_BASE}/reset`, { method: "POST" }).then(r => r.json()),
};
