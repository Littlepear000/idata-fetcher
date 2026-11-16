"""Offline tests: synthetic WEO-like data and a fake Bloomberg fetcher. No network, no imf_datatools.

Run from the fp_analysis_skills folder:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fp_analysis import aggregate, bloomberg, countries, fiscal, tools  # noqa: E402
from fp_analysis.panel import PanelError, to_annual_panel  # noqa: E402
from fp_analysis.registry import check_requirements  # noqa: E402

VALUES = {  # country -> indicator -> {year: value}
    "USA": {"NGDP": {2019: 100, 2020: 110, 2021: 121}, "GGXWDG": {2019: 50, 2020: 60, 2021: 66},
            "GGEI": {2019: 2, 2020: 2.5, 2021: 3.0}, "GGXWDG_NGDP": {2019: 50, 2020: 54.5, 2021: 54.5},
            "GGXONLB_NGDP": {2019: 0.5, 2020: -1.0, 2021: -0.2}, "NGDPD": {2019: 10, 2020: 11, 2021: 12},
            "NGDP_FY_USD": {2019: 10, 2020: 11, 2021: 12}},
    "GHA": {"NGDP": {2019: 200, 2020: 210, 2021: 220}, "GGXWDG": {2019: 100, 2020: 100, 2021: 100},
            "GGEI": {2019: 5, 2020: 5, 2021: 5}, "GGXWDG_NGDP": {2019: 50, 2020: 47.6, 2021: 45.5},
            "GGXONLB_NGDP": {2019: 1.0, 2020: 1.0, 2021: -15.0}, "NGDPD": {2019: 30, 2020: 31, 2021: 32},
            "NGDP_FY_USD": {2019: 30, 2020: 31, 2021: 32}},
}


def weo_long(indicators=None) -> pd.DataFrame:
    rows = []
    for country, series in VALUES.items():
        for code, by_year in series.items():
            if indicators and code not in indicators:
                continue
            for year, value in by_year.items():
                rows.append({"COUNTRY": country, "INDICATOR": code, "FREQUENCY": "A",
                             "dates": f"{year}-01-01", "OBS_VALUE": value, "SCALE": "Billions"})
    return pd.DataFrame(rows)


class PanelTests(unittest.TestCase):
    def test_long_to_panel(self):
        panel = to_annual_panel(weo_long())
        self.assertEqual(set(panel["country"]), {"USA", "GHA"})
        self.assertIn("GGEI", panel.columns)
        self.assertEqual(panel["year"].tolist()[:3], [2019, 2020, 2021])

    def test_quarterly_rejected(self):
        frame = weo_long()
        frame["FREQUENCY"] = "Q"
        with self.assertRaises(PanelError):
            to_annual_panel(frame)

    def test_conflicting_duplicates_rejected(self):
        frame = weo_long()
        clash = frame.iloc[[0]].assign(OBS_VALUE=999)
        with self.assertRaises(PanelError):
            to_annual_panel(pd.concat([frame, clash]))


class FiscalTests(unittest.TestCase):
    def test_r_minus_g_standard(self):
        panel = to_annual_panel(weo_long())
        out, _ = fiscal.r_minus_g(panel)
        row = out[(out.country == "USA") & (out.year == 2020)].iloc[0]
        g, r = 110 / 100 - 1, 2.5 / 50
        self.assertAlmostEqual(row["g"], g * 100)
        self.assertAlmostEqual(row["r"], r * 100)
        self.assertAlmostEqual(row["rlessg"], (r - g) / (1 + g) * 100)
        self.assertAlmostEqual(row["rlessg_abs"], (r - g) * 100)
        self.assertTrue(np.isnan(out[(out.country == "USA") & (out.year == 2019)]["rlessg"].iloc[0]))

    def test_missing_year_is_not_lagged_over(self):
        frame = weo_long()
        frame = frame[~((frame.COUNTRY == "USA") & (frame.dates == "2020-01-01"))]
        out, _ = fiscal.r_minus_g(to_annual_panel(frame))
        self.assertTrue(np.isnan(out[(out.country == "USA") & (out.year == 2021)]["rlessg"].iloc[0]))

    def test_dspb_and_outlier(self):
        panel = to_annual_panel(weo_long())
        out, notes = fiscal.dspb(panel)
        row = out[(out.country == "USA") & (out.year == 2021)].iloc[0]
        g, r = 121 / 110 - 1, 3.0 / 60
        expected = 54.5 * (r - g) / (1 + g)
        self.assertAlmostEqual(row["dspb"], expected)
        self.assertAlmostEqual(row["pb_gap"], -0.2 - expected)
        bbb = out[(out.country == "GHA") & (out.year == 2021)].iloc[0]
        self.assertTrue(bbb["gap_excluded"])
        self.assertTrue(np.isnan(bbb["pb_gap"]))
        self.assertTrue(any("outlier" in note for note in notes))


class AggregateTests(unittest.TestCase):
    def test_weighted_mean_and_coverage(self):
        frame = pd.DataFrame({"country": ["A", "B", "C"], "year": [2020] * 3,
                              "x": [1.0, 3.0, np.nan], "w": [1.0, 3.0, 4.0]})
        stats = aggregate.group_statistics(frame, "x", {"G": ["A", "B", "C"]}, "w")
        row = stats.iloc[0]
        self.assertAlmostEqual(row["weighted_mean"], (1 + 9) / 4)
        self.assertAlmostEqual(row["weight_coverage"], 50.0)
        self.assertEqual(row["n_countries"], 2)


class RequirementTests(unittest.TestCase):
    def test_missing_inputs_tell_what_to_fetch(self):
        panel = to_annual_panel(weo_long(["NGDP", "GGXWDG"]))
        check = check_requirements("r_minus_g", panel, {"start_year": 2020})
        self.assertFalse(check["ok"])
        self.assertEqual(check["fetch_in_research"]["indicators"], ["GGEI"])
        self.assertEqual(check["fetch_in_research"]["start_year"], 2019)

    def test_ratio_can_be_derived(self):
        panel = to_annual_panel(weo_long(["NGDP", "GGXWDG", "GGEI", "GGXONLB_NGDP"]))
        check = check_requirements("dspb", panel, {"groups": []})
        self.assertTrue(check["ok"])
        self.assertEqual(check["derived"], ["GGXWDG_NGDP"])

    def test_weight_needed_only_for_groups(self):
        panel = to_annual_panel(weo_long(["NGDP", "GGXWDG", "GGEI"]))
        self.assertTrue(check_requirements("r_minus_g", panel, {"groups": []})["ok"])
        check = check_requirements("r_minus_g", panel)          # default: income groups, auto weight
        self.assertFalse(check["ok"])
        self.assertIn("NGDP_FY_USD", check["questions_for_user"][0])
        self.assertEqual(check["missing"], [])                  # a question, not a missing input
        self.assertTrue(check_requirements("r_minus_g", panel, {"weight": "none"})["ok"])

    def test_fiscal_weight_rule(self):
        panel = to_annual_panel(weo_long())
        self.assertEqual(check_requirements("r_minus_g", panel)["weight"], "NGDP_FY_USD")
        stats = check_requirements("group_statistics", panel, {"indicator": "NGDP"})
        self.assertEqual(stats["weight"], "NGDPD")
        stats = check_requirements("group_statistics", panel, {"indicator": "GGXWDG_NGDP"})
        self.assertEqual(stats["weight"], "NGDP_FY_USD")

    def test_unknown_country_becomes_question(self):
        frame = weo_long()
        frame.loc[frame.COUNTRY == "GHA", "COUNTRY"] = "XYZ"
        check = check_requirements("r_minus_g", to_annual_panel(frame))
        self.assertFalse(check["ok"])
        self.assertTrue(any("XYZ" in q for q in check["questions_for_user"]))


class CountryTests(unittest.TestCase):
    def test_lookup_variants(self):
        self.assertEqual(countries.lookup("USA")["ifscode"], "111")
        self.assertEqual(countries.lookup(111)["iso3"], "USA")
        self.assertEqual(countries.lookup("652.0")["iso3"], "GHA")
        self.assertEqual(countries.lookup("Afghanistan, Islamic Republic of")["iso3"], "AFG")
        self.assertEqual(countries.lookup("Namibia")["iso2"], "NA")
        self.assertIsNone(countries.lookup("Atlantis"))

    def test_aggregates(self):
        self.assertTrue(countries.is_aggregate("G110"))
        self.assertTrue(countries.is_aggregate("World"))
        self.assertFalse(countries.is_aggregate("USA"))

    def test_income_groups(self):
        groups, info = countries.income_groups(["USA", "GHA", "BRA", "G110"])
        self.assertEqual(groups["Global"], ["USA", "GHA", "BRA"])
        self.assertEqual(groups["Advanced Economies"], ["USA"])
        self.assertEqual(groups["Emerging Markets"], ["BRA"])
        self.assertEqual(groups["Low-Income Developing Countries"], ["GHA"])
        sizes = countries.tables()["countries"]["income_group"].value_counts().to_dict()
        self.assertEqual(sizes, {"EM": 96, "LIC": 58, "AE": 43})

    def test_ifscode_data_also_grouped(self):
        groups, _ = countries.income_groups(["111", "652"])
        self.assertEqual(groups["Advanced Economies"], ["111"])


def fake_fetcher(calls):
    def fetch(database, key, start, end):
        calls.append(key)
        tickers = key.rsplit(".PX_LAST.D", 1)[0].split("+")
        index = pd.date_range("2024-01-01", "2024-03-31", freq="D", name="dates")
        return pd.DataFrame({f"{t}.PX_LAST.D": np.arange(len(index), dtype=float) for t in tickers}, index=index)
    return fetch


class BloombergTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / "t.csv"
        rows = ["ticker,country,iso3,ifscode,active"] + [f"T{i} Index,Country {i},C{i:02d},{i},1" for i in range(30)]
        path.write_text("\n".join(rows))
        self.path = path

    def tearDown(self):
        self.tmp.cleanup()

    def test_chunking_and_monthly_average(self):
        calls = []
        frame, lineage = bloomberg.fetch_series("bond_yield_10y", "M", ticker_path=self.path,
                                                fetcher=fake_fetcher(calls))
        self.assertEqual(len(calls), 2)                       # 25 + 5 tickers
        self.assertTrue(calls[0].startswith("T0_INDEX+T1_INDEX"))
        jan = frame[(frame.ticker == "T0_INDEX") & (frame.TIME_PERIOD == "2024-01")].iloc[0]
        self.assertAlmostEqual(jan["OBS_VALUE"], 15.0)        # mean of 0..30
        self.assertEqual(jan["n_daily_obs"], 31)
        self.assertEqual(frame["COUNTRY"].nunique(), 30)

    def test_quarter_labels_and_country_filter(self):
        frame, _ = bloomberg.fetch_series("embig_spreads", "Q", ticker_path=self.path,
                                          countries=["c01", "Country 2"], fetcher=fake_fetcher([]))
        self.assertEqual(sorted(frame["COUNTRY"].unique()), ["C01", "C02"])
        self.assertEqual(frame["TIME_PERIOD"].unique().tolist(), ["2024-Q1"])

    def test_iso3_filled_from_country_table(self):
        path = Path(self.tmp.name) / "embig.csv"
        path.write_text("ticker,country,ifscode\nX1 Index,Brazil,223\nX2 Index,Global,1\n")
        table = bloomberg.load_ticker_table("embig_spreads", path)
        self.assertEqual(table["iso3"].tolist(), ["BRA", ""])

    def test_unknown_country(self):
        with self.assertRaises(ValueError):
            bloomberg.fetch_series("embig_spreads", "M", ticker_path=self.path, countries=["Atlantis"],
                                   fetcher=fake_fetcher([]))


class ToolTests(unittest.TestCase):
    def setUp(self):
        tools.configure(group_expander=lambda name: {"countries": {"Group A": ["USA"], "Group B": ["GHA"]}[name]},
                        output_saver=lambda handoff, output: None)
        self.handoff = {"id": "handoff_test", "outputs": {}, "datasets": [
            {"id": "ds_1", "title": "WEO fiscal", "rows": 0, "columns": [], "frame": weo_long()}]}

    def test_run_r_minus_g_with_groups(self):
        result = tools.analysis_tool_result("run_analysis_skill", {
            "skill_id": "r_minus_g", "dataset_ids": ["ds_1"], "output_name": "rg",
            "params": {"groups": ["Group A", "Group B"], "start_year": 2020}}, self.handoff, persist=False)
        self.assertTrue(result["executed"])
        self.assertEqual(sorted(self.handoff["outputs"]), ["rg_chart", "rg_country", "rg_groups"])
        chart = self.handoff["outputs"]["rg_chart"]["frame"]
        self.assertEqual(list(chart.columns), ["year", "All countries (in selected groups)", "Group A", "Group B"])

    def test_run_refuses_when_missing(self):
        self.handoff["datasets"][0]["frame"] = weo_long(["NGDP"])
        result = tools.analysis_tool_result("run_analysis_skill", {
            "skill_id": "dspb", "dataset_ids": ["ds_1"], "output_name": "d"}, self.handoff, persist=False)
        self.assertFalse(result["executed"])
        self.assertIn("fetch_in_research", result)
        self.assertEqual(self.handoff["outputs"], {})

    def test_dspb_outputs(self):
        result = tools.analysis_tool_result("run_analysis_skill", {
            "skill_id": "dspb", "dataset_ids": ["ds_1"], "output_name": "d",
            "params": {"groups": ["Group A", "Group B"]}}, self.handoff, persist=False)
        self.assertTrue(result["executed"])
        self.assertEqual(sorted(self.handoff["outputs"]), ["d_country", "d_group_means", "d_summary"])

    def test_default_income_groups_and_fiscal_weight(self):
        result = tools.analysis_tool_result("run_analysis_skill", {
            "skill_id": "r_minus_g", "dataset_ids": ["ds_1"], "output_name": "rg"}, self.handoff, persist=False)
        self.assertTrue(result["executed"], result)
        chart = self.handoff["outputs"]["rg_chart"]["frame"]
        self.assertEqual(list(chart.columns), ["year", "Global", "Advanced Economies", "Emerging Markets",
                                               "Low-Income Developing Countries"])
        groups = self.handoff["outputs"]["rg_groups"]["frame"]
        row = groups[(groups.group == "Global") & (groups.year == 2021)].iloc[0]
        country = self.handoff["outputs"]["rg_country"]["frame"]
        sub = country[country.year == 2021]
        expected = (sub.rlessg_abs * sub.NGDP_FY_USD).sum() / sub.NGDP_FY_USD.sum()
        self.assertAlmostEqual(row["weighted_mean"], expected)

    def test_question_stops_run(self):
        self.handoff["datasets"][0]["frame"] = weo_long(["NGDP", "GGXWDG", "GGEI", "NGDPD"])
        result = tools.analysis_tool_result("run_analysis_skill", {
            "skill_id": "r_minus_g", "dataset_ids": ["ds_1"], "output_name": "rg"}, self.handoff, persist=False)
        self.assertFalse(result["executed"])
        self.assertIn("NGDPD", result["questions_for_user"][0])   # offered as the alternative
        result = tools.analysis_tool_result("run_analysis_skill", {
            "skill_id": "r_minus_g", "dataset_ids": ["ds_1"], "output_name": "rg",
            "params": {"weight": "NGDPD"}}, self.handoff, persist=False)
        self.assertTrue(result["executed"])

    def test_lookup_tool(self):
        result = tools.analysis_tool_result("lookup_team_countries", {"query": ["Ghana", "XYZ"], "group": "AE"},
                                            self.handoff)
        self.assertEqual(result["matches"][0]["income_group"], "LIC")
        self.assertEqual(result["unmatched"], ["XYZ"])
        self.assertEqual(result["group"]["count"], 43)

    def test_research_tool_sets_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.csv"
            path.write_text("ticker,country,iso3,ifscode\nUSGG10YR Index,United States,USA,111\n")
            tools.configure(fetcher=fake_fetcher([]), ticker_paths={"bond_yield_10y": str(path)})
            state: dict = {}
            result = tools.research_tool_result("fetch_bond_yield_10y", {
                "frequency": "M", "start_period": None, "end_period": None, "countries": None}, state)
        self.assertEqual(result["retrieval_id"], "retrieval_1")
        self.assertEqual(len(state["frame"]), 3)
        self.assertIn("retrieval_1", state["retrieved_frames"])


if __name__ == "__main__":
    unittest.main()
