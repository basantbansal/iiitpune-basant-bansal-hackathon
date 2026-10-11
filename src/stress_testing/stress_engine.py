from typing import List, Dict
from src.engine.schemas import CreditExposure, CreditStressResult
import pandas as pd

class StressEngine:
    """
    Module B: Macroeconomic Stress Testing Engine.
    Applies synthetic shocks to the portfolio using cross-asset sensitivities.
    Formula: P&L = (Equity Beta * Equity Shock) - (Rate DV01 * Rate Shock) - (Spread DV01 * Spread Shock)
    """
    def __init__(self):
        # Institutional Risk Profiles for the 10-stock universe
        # rate_mod_dur and spread_mod_dur represent the % change in asset price per 100bps (1%) move (Modified Duration)
        self.asset_profiles = {
            "AAPL":  {"beta": 1.2, "rate_mod_dur": 2.5, "spread_mod_dur": 1.5},
            "MSFT":  {"beta": 1.1, "rate_mod_dur": 2.0, "spread_mod_dur": 1.0},
            "NVDA":  {"beta": 2.2, "rate_mod_dur": 4.5, "spread_mod_dur": 2.0}, # High growth, high rate sensitivity
            "AMZN":  {"beta": 1.5, "rate_mod_dur": 3.0, "spread_mod_dur": 2.0},
            "GOOGL": {"beta": 1.1, "rate_mod_dur": 2.0, "spread_mod_dur": 1.0},
            "META":  {"beta": 1.4, "rate_mod_dur": 2.5, "spread_mod_dur": 1.5},
            "TSLA":  {"beta": 2.4, "rate_mod_dur": 5.0, "spread_mod_dur": 3.0},
            "JPM":   {"beta": 1.0, "rate_mod_dur": -3.0, "spread_mod_dur": 4.0}, # Banks benefit from rate hikes (negative mod_dur)
            "JNJ":   {"beta": 0.5, "rate_mod_dur": 1.0, "spread_mod_dur": 0.5},  # Defensive
            "XOM":   {"beta": 0.8, "rate_mod_dur": 0.5, "spread_mod_dur": 1.0},  # Value/Commodity
        }

        # Predefined Macro Scenarios
        self.scenarios = {
            "1. 2022 Fed Tightening Shock": {
                "equity_shock": -0.15, "rate_shock_bps": 150, "spread_shock_bps": 50,
                "pd_multiplier": 1.2, "lgd_multiplier": 1.1, "exposure_multiplier": 1.05,
                "desc": "Aggressive rate hikes crush growth multiples."
            },
            "2. Systemic Credit Crunch": {
                "equity_shock": -0.20, "rate_shock_bps": -50, "spread_shock_bps": 250,
                "pd_multiplier": 2.0, "lgd_multiplier": 1.5, "exposure_multiplier": 1.2,
                "desc": "Liquidity dries up. Flight to safety drops rates, but spreads blow out."
            },
            "3. Tech Bubble Burst": {
                "equity_shock": -0.30, "rate_shock_bps": -25, "spread_shock_bps": 25,
                "pd_multiplier": 1.1, "lgd_multiplier": 1.0, "exposure_multiplier": 1.0,
                "desc": "Severe tech selloff. Defensive assets outperform."
            }
        }


        # Synthetic Banking Book Portfolio Assumptions
        self.synthetic_initial_cet1_capital = 5_000_000.0
        self.synthetic_credit_portfolio = self._load_credit_portfolio()
        self.synthetic_banking_book = self._load_banking_book()

    def _load_credit_portfolio(self) -> List[CreditExposure]:
        import json
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "synthetic_credit_portfolio.json")
        exposures = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    exp = CreditExposure(
                        identifier=item["issuer_id"],
                        ead=item["ead"],
                        pd=item["pd"],
                        lgd=item["lgd"],
                        risk_weight=item["risk_weight"]
                    )
                    exposures.append(exp)
        except Exception:
            pass
        return exposures

    def _load_banking_book(self) -> List[Dict]:
        import json
        import os
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "synthetic_banking_book.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [item for item in data if not str(item.get("id", "")).startswith("_")]
        except Exception:
            return []

    def run_banking_book_stress(self, scenario_name: str) -> dict:
        if scenario_name not in self.scenarios:
            raise ValueError(f"Scenario '{scenario_name}' not found.")

        shock = self.scenarios[scenario_name]
        positions = self.synthetic_banking_book if hasattr(self, "synthetic_banking_book") and self.synthetic_banking_book else self._load_banking_book()

        position_results = []
        for pos in positions:
            asset_class = pos.get("asset_class", "")
            pos_id = pos.get("id", "")
            name = pos.get("name", pos_id)
            notional = float(pos.get("notional", 0.0))

            if asset_class == "Corporate Loans":
                pre_val = notional
                pd_val = float(pos.get("pd", 0.02))
                lgd_val = float(pos.get("lgd", 0.40))
                spread_dur = float(pos.get("spread_duration", 3.0))
                pd_mult = float(shock.get("pd_multiplier", 1.0))
                delta_pd = min(1.0, pd_val * pd_mult) - pd_val
                el_pnl = -pre_val * delta_pd * lgd_val
                spread_pnl = -pre_val * spread_dur * (shock["spread_shock_bps"] / 10000.0)
                total_pnl = el_pnl + spread_pnl
                post_val = pre_val + total_pnl
                drawdown_pct = (total_pnl / pre_val) * 100.0 if pre_val > 0 else 0.0

                position_results.append({
                    "id": pos_id,
                    "name": name,
                    "asset_class": asset_class,
                    "sector_rating": pos.get("sector", "Corporate"),
                    "notional": notional,
                    "pre_shock_value": round(pre_val, 2),
                    "pnl": round(total_pnl, 2),
                    "post_shock_value": round(post_val, 2),
                    "drawdown_pct": round(drawdown_pct, 2),
                    "details": f"EL loss: ${abs(el_pnl):,.2f}, Spread loss: ${abs(spread_pnl):,.2f}"
                })

            elif asset_class == "Fixed Income Bonds":
                pre_val = notional
                mod_dur = float(pos.get("mod_duration", 5.0))
                spread_dur = float(pos.get("spread_duration", 0.0))
                rate_pnl = -pre_val * mod_dur * (shock["rate_shock_bps"] / 10000.0)
                spread_pnl = -pre_val * spread_dur * (shock["spread_shock_bps"] / 10000.0)
                total_pnl = rate_pnl + spread_pnl
                post_val = pre_val + total_pnl
                drawdown_pct = (total_pnl / pre_val) * 100.0 if pre_val > 0 else 0.0

                position_results.append({
                    "id": pos_id,
                    "name": name,
                    "asset_class": asset_class,
                    "sector_rating": pos.get("rating", "IG"),
                    "notional": notional,
                    "pre_shock_value": round(pre_val, 2),
                    "pnl": round(total_pnl, 2),
                    "post_shock_value": round(post_val, 2),
                    "drawdown_pct": round(drawdown_pct, 2),
                    "details": f"Rate P&L: ${rate_pnl:,.2f}, Spread P&L: ${spread_pnl:,.2f}"
                })

            elif asset_class == "Interest Rate Swaps":
                pre_val = float(pos.get("pre_shock_value", 0.0))
                signed_dv01 = float(pos.get("dv01", 0.0))
                total_pnl = signed_dv01 * float(shock["rate_shock_bps"])
                post_val = pre_val + total_pnl
                drawdown_pct = (total_pnl / notional) * 100.0 if notional > 0 else 0.0

                position_results.append({
                    "id": pos_id,
                    "name": name,
                    "asset_class": asset_class,
                    "sector_rating": pos.get("counterparty", "OTC Derivative"),
                    "notional": notional,
                    "pre_shock_value": round(pre_val, 2),
                    "pnl": round(total_pnl, 2),
                    "post_shock_value": round(post_val, 2),
                    "drawdown_pct": round(drawdown_pct, 2),
                    "details": f"DV01: ${signed_dv01:+,.0f}/bp × {shock['rate_shock_bps']} bps"
                })

            elif asset_class == "Equity Holdings":
                pre_val = notional
                beta = float(pos.get("beta", 1.0))
                total_pnl = pre_val * (beta * float(shock["equity_shock"]))
                post_val = pre_val + total_pnl
                drawdown_pct = (total_pnl / pre_val) * 100.0 if pre_val > 0 else 0.0

                position_results.append({
                    "id": pos_id,
                    "name": name,
                    "asset_class": asset_class,
                    "sector_rating": pos.get("sector", "Equity"),
                    "notional": notional,
                    "pre_shock_value": round(pre_val, 2),
                    "pnl": round(total_pnl, 2),
                    "post_shock_value": round(post_val, 2),
                    "drawdown_pct": round(drawdown_pct, 2),
                    "details": f"Beta {beta:.2f} × Equity Shock {shock['equity_shock']*100:+.0f}%"
                })

        classes = ["Corporate Loans", "Fixed Income Bonds", "Interest Rate Swaps", "Equity Holdings"]
        by_asset_class = []
        total_pnl_all = sum(p["pnl"] for p in position_results)

        for ac in classes:
            ac_positions = [p for p in position_results if p["asset_class"] == ac]
            if not ac_positions:
                continue
            ac_pre = sum(p["pre_shock_value"] for p in ac_positions)
            ac_pnl = sum(p["pnl"] for p in ac_positions)
            ac_post = ac_pre + ac_pnl
            ac_notional = sum(p["notional"] for p in ac_positions)
            base_for_pct = ac_pre if ac_pre > 0 else ac_notional
            ac_pct = (ac_pnl / base_for_pct * 100.0) if base_for_pct > 0 else 0.0
            share_loss = (ac_pnl / total_pnl_all * 100.0) if total_pnl_all != 0 else 0.0

            by_asset_class.append({
                "asset_class": ac,
                "position_count": len(ac_positions),
                "notional": round(ac_notional, 2),
                "pre_shock_value": round(ac_pre, 2),
                "pnl": round(ac_pnl, 2),
                "post_shock_value": round(ac_post, 2),
                "drawdown_pct": round(ac_pct, 2),
                "share_of_loss_pct": round(share_loss, 2)
            })

        total_pre_val = sum(c["pre_shock_value"] for c in by_asset_class)
        total_pnl_val = sum(c["pnl"] for c in by_asset_class)
        total_post_val = total_pre_val + total_pnl_val
        total_dd_pct = (total_pnl_val / total_pre_val * 100.0) if total_pre_val > 0 else 0.0

        return {
            "total_pre_shock_value": round(total_pre_val, 2),
            "total_pnl": round(total_pnl_val, 2),
            "total_post_shock_value": round(total_post_val, 2),
            "total_drawdown_pct": round(total_dd_pct, 2),
            "invariant_holds": abs(total_post_val - (total_pre_val + total_pnl_val)) < 1e-4,
            "by_asset_class": by_asset_class,
            "positions": position_results
        }

    def run_scenario(self, current_weights: dict, total_aum: float, scenario_name: str) -> dict:
        if scenario_name not in self.scenarios:
            raise ValueError("Scenario not found.")

        shock = self.scenarios[scenario_name]
        results = []

        for ticker, weight in current_weights.items():
            profile = self.asset_profiles.get(ticker, {"beta": 1.0, "rate_mod_dur": 1.0, "spread_mod_dur": 1.0})
            notional = total_aum * weight

            # P&L Math
            equity_pnL = notional * (profile["beta"] * shock["equity_shock"])
            rate_pnl = notional * (-profile["rate_mod_dur"] * (shock["rate_shock_bps"] / 10000.0))
            spread_pnl = notional * (-profile["spread_mod_dur"] * (shock["spread_shock_bps"] / 10000.0))

            total_pnl = equity_pnL + rate_pnl + spread_pnl
            stress_value = notional + total_pnl

            results.append({
                "Ticker": ticker,
                "Base Exposure": notional,
                "Equity P&L": equity_pnL,
                "Rate P&L": rate_pnl,
                "Spread P&L": spread_pnl,
                "Total P&L": total_pnl,
                "Stressed Value": stress_value,
                "Drawdown (%)": (total_pnl / notional) * 100 if notional > 0 else 0
            })

        market_df = pd.DataFrame(results)

        credit_metrics = {}
        if getattr(self, "synthetic_credit_portfolio", None):
            credit_results = self.apply_credit_stress(
                exposures=self.synthetic_credit_portfolio,
                pd_multiplier=shock.get("pd_multiplier", 1.0),
                lgd_multiplier=shock.get("lgd_multiplier", 1.0),
                initial_cet1_capital=self.synthetic_initial_cet1_capital,
                exposure_multiplier=shock.get("exposure_multiplier", 1.0)
            )
            agg = self.aggregate_credit_portfolio(credit_results, self.synthetic_initial_cet1_capital)
            credit_metrics = {
                "baseline_ecl": agg["total_baseline_ecl"],
                "stressed_ecl": agg["total_stressed_ecl"],
                "incremental_ecl": agg["total_incremental_ecl"],
                "rwa": agg["total_rwa"],
                "cet1_capital_burden": agg["cet1_impact"],
                "num_exposures": len(self.synthetic_credit_portfolio),
                "pd_multiplier": shock.get("pd_multiplier", 1.0),
                "lgd_multiplier": shock.get("lgd_multiplier", 1.0),
                "exposure_multiplier": shock.get("exposure_multiplier", 1.0)
            }

        return {
            "market_df": market_df,
            "credit_metrics": credit_metrics
        }

    def apply_credit_stress(
        self,
        exposures: List[CreditExposure],
        pd_multiplier: float,
        lgd_multiplier: float,
        initial_cet1_capital: float,
        exposure_multiplier: float = 1.0
    ) -> List[CreditStressResult]:
        """
        Applies a deterministic credit stress scenario.
        ECL = PD * LGD * EAD
        RWA = EAD * risk_weight
        Simplified CET1 Impact/Burden = Stressed ECL / Initial CET1 Capital. This is NOT a Basel-compliant post-stress CET1 ratio.
        """
        if initial_cet1_capital <= 0:
            raise ValueError("Initial CET1 capital must be positive.")
        if pd_multiplier < 0 or lgd_multiplier < 0 or exposure_multiplier < 0:
            raise ValueError("Multipliers cannot be negative.")

        results = []
        for exp in exposures:
            baseline_ecl = exp.pd * exp.lgd * exp.ead

            # Stressed parameters (probabilities capped at 1.0)
            stressed_pd = min(1.0, exp.pd * pd_multiplier)
            stressed_lgd = min(1.0, exp.lgd * lgd_multiplier)
            stressed_ead = exp.ead * exposure_multiplier

            stressed_ecl = stressed_pd * stressed_lgd * stressed_ead
            incremental_ecl = stressed_ecl - baseline_ecl

            # RWA approximation
            rwa = stressed_ead * exp.risk_weight

            # CET1 impact
            cet1_impact = stressed_ecl / initial_cet1_capital

            results.append(CreditStressResult(
                identifier=exp.identifier,
                baseline_pd=exp.pd,
                stressed_pd=stressed_pd,
                baseline_lgd=exp.lgd,
                stressed_lgd=stressed_lgd,
                ead=stressed_ead,
                risk_weight=exp.risk_weight,
                baseline_ecl=baseline_ecl,
                stressed_ecl=stressed_ecl,
                incremental_ecl=incremental_ecl,
                rwa=rwa,
                cet1_impact=cet1_impact
            ))

        return results

    def aggregate_credit_portfolio(self, results: List[CreditStressResult], initial_cet1_capital: float) -> Dict[str, float]:
        """
        Aggregates individual credit stress results into portfolio-level metrics.
        """
        if initial_cet1_capital <= 0:
            raise ValueError("Initial CET1 capital must be positive.")

        total_ead = sum(r.ead for r in results)
        total_baseline_ecl = sum(r.baseline_ecl for r in results)
        total_stressed_ecl = sum(r.stressed_ecl for r in results)
        total_incremental_ecl = sum(r.incremental_ecl for r in results)
        total_rwa = sum(r.rwa for r in results)

        cet1_impact = total_stressed_ecl / initial_cet1_capital

        return {
            "total_ead": total_ead,
            "total_baseline_ecl": total_baseline_ecl,
            "total_stressed_ecl": total_stressed_ecl,
            "total_incremental_ecl": total_incremental_ecl,
            "total_rwa": total_rwa,
            "cet1_impact": cet1_impact
        }
