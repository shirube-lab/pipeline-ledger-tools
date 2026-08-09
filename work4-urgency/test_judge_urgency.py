"""Unit tests for judge_urgency.py (stdlib only — run: python test_judge_urgency.py).

The first test reproduces the worked example printed in the guideline
itself (H25 参考資料3 表2.7, Ⅲ-43): 25 pipes with a=6, b=3, c=2 gives an
a-rate of 24% >= 20% and therefore span rank A.
"""

from __future__ import annotations

import pandas as pd

from judge_urgency import (
    dedupe_same_location,
    judge_span,
    load_criteria,
    rate_rank,
    validate,
    worst,
)
from pathlib import Path

CRITERIA = load_criteria(Path(__file__).parent / "criteria" / "default_h21.json")
TH = CRITERIA["rate_thresholds"]

PASSED = 0


def check(name: str, cond: bool) -> None:
    global PASSED
    assert cond, f"FAILED: {name}"
    PASSED += 1
    print(f"ok: {name}")


def make_span(n_pipes: int = 25, material: str = "rc") -> pd.Series:
    return pd.Series({"span_id": "S1", "material": material,
                      "diameter_mm": 900, "length_m": 50.0, "n_pipes": n_pipes})


def defects(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["span_id", "pipe_no", "distance_m", "item", "rank"])


def pipes(ranks: dict[str, int]) -> list[tuple]:
    """Spread n pipes of each rank over distinct pipe numbers (item=クラック)."""
    rows, no = [], 1
    for rank, n in ranks.items():
        for _ in range(n):
            rows.append(("S1", no, float(no), "クラック", rank))
            no += 1
    return rows


# --- rate_rank: the guideline's own worked example -------------------------
rank, rates = rate_rank(25, ["a"] * 6 + ["b"] * 3 + ["c"] * 2, TH)
check("計算例(H25参考資料3 Ⅲ-43): 25本中a6/b3/c2 → a率24% → A",
      rank == "A" and rates["a_pct"] == 24.0)

# --- rate boundaries -------------------------------------------------------
check("a率ちょうど20% → A", rate_rank(10, ["a"] * 2, TH)[0] == "A")
check("a+b率ちょうど40% → A", rate_rank(10, ["a"] + ["b"] * 3, TH)[0] == "A")
check("a率10%・ab率10%(閾値未満) → B", rate_rank(10, ["a"], TH)[0] == "B")
check("b率30%のみ → B", rate_rank(10, ["b"] * 3, TH)[0] == "B")
check("cのみ60% → B", rate_rank(10, ["c"] * 6, TH)[0] == "B")
check("cのみ50% → C", rate_rank(10, ["c"] * 5, TH)[0] == "C")
check("不良なし → ランクなし", rate_rank(10, [], TH)[0] is None)

# --- worst / dedupe --------------------------------------------------------
check("worst(a/b/c)=a", worst(["c", "a", "b"], ["a", "b", "c"]) == "a")
dd = dedupe_same_location(defects([("S1", 7, 12.5, "クラック", "a"),
                                   ("S1", 7, 12.5, "浸入水", "b")]))
check("同一箇所の複数不良は最上位のみ(備考③)",
      len(dd) == 1 and dd.iloc[0]["item"] == "クラック" and dd.iloc[0]["dedup_note"] != "")

# --- special rule: single 破損a forces rank A ------------------------------
res = judge_span(make_span(30), defects([("S1", 3, 5.0, "破損", "a")]), CRITERIA)
check("破損a×1(発生率3%)でも特例で発生率ランクA → 緊急度Ⅱ(備考②)",
      res["発生率ランク"] == "A" and res["特例適用"] == "○" and res["緊急度"] == "Ⅱ")

res = judge_span(make_span(30),
                 defects([("S1", 3, 5.0, "継手ズレ", "a"), ("S1", None, None, "腐食", "A")]),
                 CRITERIA)
check("継手ズレa+腐食A → A2項目 → 緊急度Ⅰ", res["緊急度"] == "Ⅰ")

# --- urgency composition ---------------------------------------------------
res = judge_span(make_span(), defects([("S1", None, None, "たるみ", "B"),
                                       ("S1", None, None, "腐食", "B")]), CRITERIA)
check("B2項目 → 緊急度Ⅱ", res["緊急度"] == "Ⅱ")

res = judge_span(make_span(), defects([("S1", None, None, "腐食", "B")]), CRITERIA)
check("B1項目のみ → 緊急度Ⅲ", res["緊急度"] == "Ⅲ")

res = judge_span(make_span(), defects(pipes({"c": 2})), CRITERIA)
check("cランク少数のみ(発生率C) → 緊急度Ⅲ", res["発生率ランク"] == "C" and res["緊急度"] == "Ⅲ")

res = judge_span(make_span(), defects([]), CRITERIA)
check("不良ゼロ → 異常なし", res["緊急度"] == "異常なし")

# --- guideline example as a full span judgment -----------------------------
res = judge_span(make_span(25), defects(pipes({"a": 6, "b": 3, "c": 2})), CRITERIA)
check("計算例スパン(発生率A・腐食たるみなし) → A1項目 → 緊急度Ⅱ", res["緊急度"] == "Ⅱ")

# --- validation ------------------------------------------------------------
span_df = pd.DataFrame([{"span_id": "S1", "material": "ceramic", "diameter_mm": 300,
                         "length_m": 30.0, "n_pipes": 30}])
bad = pd.DataFrame([
    {"span_id": "S1", "pipe_no": 1, "distance_m": 1.0, "item": "破損", "rank": "c"},
    {"span_id": "S1", "pipe_no": 2, "distance_m": 2.0, "item": "腐食", "rank": "a"},
    {"span_id": "S1", "pipe_no": 3, "distance_m": 3.0, "item": "謎項目", "rank": "a"},
    {"span_id": "S9", "pipe_no": 4, "distance_m": 4.0, "item": "破損", "rank": "a"},
])
errs = validate(span_df, bad, CRITERIA)
check("バリデーション: 陶管の破損c(未定義)/腐食のa(大文字必須)/未定義項目/不明スパンの4件検出",
      len(errs) == 4)

print(f"\nall {PASSED} tests passed")
