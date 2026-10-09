import pytest
from src.rebalancer.index_rebalancer import IndexRebalancer

def test_infeasible_min_weight():
    with pytest.raises(ValueError, match="Infeasible constraints"):
        # 10 assets, min=0.15 => sum=1.5 > 1.0
        IndexRebalancer(min_weight=0.15)

def test_infeasible_max_weight():
    with pytest.raises(ValueError, match="Infeasible constraints"):
        # 10 assets, max=0.05 => max_sum=0.5 < 1.0
        IndexRebalancer(max_weight=0.05)
