"""
Offline unit tests for the tool layer, run against the mock imf_datatools package.

    python -m unittest discover -s idata_agent/tests -t .        (from the repository root)

They cover the rules the architecture depends on: dimension-generic specs, key derivation,
fuzzy database matching, metadata-list-first indicator search with lookup boost, the
execution precondition exposed by the spec, template rendering, and the 90-day cache.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest

from idata_agent.evals import mock_idata

mock_idata.install()  # must precede any import that calls the SDK

from idata_agent.cli import envelope  # noqa: E402
from idata_agent.codegen.render import render  # noqa: E402
from idata_agent.spec import DimensionSlot, QuerySpec  # noqa: E402
from idata_agent.tools import IMPLEMENTATIONS, discovery, implementation, resolve  # noqa: E402
from idata_agent.tools.cache import CodebookCache  # noqa: E402
from idata_agent.tools.schemas import TOOLS_BY_NAME, to_openai_tools  # noqa: E402

WEO = "IMF.RES.WEO:WEO_LIVE"
CPI = "IMF.STA:CPI"


def _tmp_cache() -> CodebookCache:
    return CodebookCache(cache_dir=tempfile.mkdtemp(prefix="idata_cache_"))


def _weo_spec(stage="confirmed", **overrides) -> QuerySpec:
    spec = QuerySpec(
        database=WEO,
        dimensions=[
            DimensionSlot("COUNTRY", ["USA", "JPN"], "the US and Japan", {"USA": "United States", "JPN": "Japan"}, True),
            DimensionSlot("INDICATOR", ["NGDP_RPCH"], "real GDP growth", {"NGDP_RPCH": mock_idata.WEO_INDICATORS["NGDP_RPCH"]}, True),
            DimensionSlot("FREQUENCY", ["A"], None, {"A": "Annual"}, True),
        ],
        start="2015",
        end="2026",
        stage=stage,
        output_dir=tempfile.mkdtemp(prefix="idata_out_"),
    )
    for k, v in overrides.items():
        setattr(spec, k, v)
    return spec


class SpecTests(unittest.TestCase):
    def test_defaults_are_long_csv_python(self):
        spec = QuerySpec()
        self.assertEqual((spec.layout, spec.file_format, spec.language, spec.stage), ("long", "csv", "python", "draft"))

    def test_key_is_derived_from_dimensions_in_order(self):
        self.assertEqual(_weo_spec().key, "USA+JPN.NGDP_RPCH.A")

    def test_several_indicators_share_one_key(self):
        spec = _weo_spec()
        spec.dimensions[1].values = ["NGDP_RPCH", "PCPIPCH"]
        self.assertEqual(spec.key, "USA+JPN.NGDP_RPCH+PCPIPCH.A")

    def test_open_dimension_gives_empty_segment(self):
        spec = _weo_spec()
        spec.dimensions[0].values = []
        self.assertEqual(spec.key, ".NGDP_RPCH.A")

    def test_validate_reports_missing_dates_and_unresolved(self):
        spec = _weo_spec(start=None)
        spec.dimensions[1].resolved = False
        problems = " ".join(spec.validate())
        self.assertIn("start and end", problems)
        self.assertIn("INDICATOR is not resolved", problems)

    def test_all_open_is_rejected(self):
        spec = _weo_spec()
        for d in spec.dimensions:
            d.values = []
        self.assertTrue(any("every dimension is open" in p for p in spec.validate()))

    def test_execution_precondition_requires_confirmation(self):
        problems = _weo_spec(stage="resolved").missing_for_execution()
        self.assertTrue(any("confirm" in p for p in problems))
        self.assertEqual(_weo_spec(stage="confirmed").missing_for_execution(), [])

    def test_roundtrip_json(self):
        spec = _weo_spec()
        again = QuerySpec.from_json(spec.to_json())
        self.assertEqual(again.key, spec.key)
        self.assertEqual(again.dimensions[1].labels, spec.dimensions[1].labels)

    def test_default_filename(self):
        self.assertEqual(_weo_spec().default_filename(), "WEO_LIVE_USA+JPN_NGDP_RPCH_A_2015-2026.csv")


class DatabaseSearchTests(unittest.TestCase):
    def test_abbreviation_weo_ranks_weo_databases_first(self):
        out = discovery.find_databases("WEO", cache=_tmp_cache())
        top2 = {c["id"] for c in out["candidates"][:2]}
        self.assertEqual(top2, {WEO, "IMF.RES:WEO"})

    def test_weo_live_prefers_live(self):
        out = discovery.find_databases("weo live", cache=_tmp_cache())
        self.assertEqual(out["candidates"][0]["id"], WEO)

    def test_cpi_informal_name(self):
        out = discovery.find_databases("cpi", cache=_tmp_cache())
        self.assertEqual(out["candidates"][0]["id"], CPI)

    def test_exact_id_scores_one(self):
        out = discovery.find_databases("IMF.STA:CPI", cache=_tmp_cache())
        self.assertEqual(out["candidates"][0]["id"], CPI)
        self.assertEqual(out["candidates"][0]["score"], 1.0)

    def test_empty_phrase_is_an_error(self):
        res = envelope(discovery.find_databases, phrase="", cache=_tmp_cache())
        self.assertFalse(res["ok"])
        self.assertIn("ask them first", res["error"]["message"])

    def test_catalogue_is_cached(self):
        cache = _tmp_cache()
        utils = mock_idata.sys.modules["imf_datatools.idata_utilities"]
        before = len([c for c in utils.calls if c[0] == "get_databases"])
        discovery.find_databases("weo", cache=cache)
        discovery.find_databases("cpi", cache=cache)
        after = len([c for c in utils.calls if c[0] == "get_databases"])
        self.assertEqual(after - before, 1)


class DiscoveryTests(unittest.TestCase):
    def test_get_dimensions_in_key_order(self):
        out = discovery.get_dimensions(CPI)
        self.assertEqual(out["key_template"], "COUNTRY.INDEX_TYPE.COICOP_1999.TYPE_OF_TRANSFORMATION.FREQUENCY")

    def test_search_values_ranks_real_gdp_growth_first(self):
        out = discovery.search_values(WEO, "INDICATOR", "real GDP growth", cache=_tmp_cache())
        self.assertEqual(out["candidates"][0]["code"], "NGDP_RPCH")
        self.assertEqual(out["total_values"], len(mock_idata.WEO_INDICATORS))

    def test_search_values_inflation_via_abbreviation_table(self):
        out = discovery.search_values(WEO, "INDICATOR", "inflation", cache=_tmp_cache())
        top5 = [c["code"] for c in out["candidates"][:5]]
        self.assertIn("PCPIPCH", top5)

    def test_fiscal_balance_surfaces_both_candidates(self):
        out = discovery.search_values(WEO, "INDICATOR", "fiscal balance", cache=_tmp_cache())
        top5 = [c["code"] for c in out["candidates"][:5]]
        self.assertIn("GGXCNL_NGDP", top5)
        self.assertIn("GGXONLB_NGDP", top5)

    def test_lookup_boost_only_applies_to_codes_in_the_list(self):
        values = [{"code": "NGDP_RPCH", "name": "Gross domestic product, constant prices, percent change"}]
        ranked = discovery.rank_values(values, "gdp growth", boosted_codes=["NGDP_RPCH", "NOT_IN_LIST"])
        self.assertEqual([r["code"] for r in ranked], ["NGDP_RPCH"])
        self.assertTrue(ranked[0]["boosted"])

    def test_typed_code_scores_one(self):
        out = discovery.search_values(WEO, "INDICATOR", "NGDP_RPCH", cache=_tmp_cache())
        self.assertEqual(out["candidates"][0]["code"], "NGDP_RPCH")
        self.assertGreaterEqual(out["candidates"][0]["score"], 1.0)

    def test_country_search(self):
        out = discovery.search_values(WEO, "COUNTRY", "Japan", cache=_tmp_cache())
        self.assertEqual(out["candidates"][0]["code"], "JPN")

    def test_cpi_transformation_hint(self):
        out = discovery.search_values(CPI, "TYPE_OF_TRANSFORMATION", "year on year inflation", cache=_tmp_cache())
        self.assertEqual(out["candidates"][0]["code"], "YOY_PCH_PA_PT")


class CacheTests(unittest.TestCase):
    def test_second_call_reads_cache_not_sdk(self):
        cache = _tmp_cache()
        utils = mock_idata.sys.modules["imf_datatools.idata_utilities"]
        before = len([c for c in utils.calls if c[0] == "get_dimension_values"])
        cache.values(WEO, "INDICATOR")
        cache.values(WEO, "INDICATOR")
        after = len([c for c in utils.calls if c[0] == "get_dimension_values"])
        self.assertEqual(after - before, 1)
        self.assertTrue(cache.status(WEO, "INDICATOR")["fresh"])

    def test_stale_entry_is_refetched(self):
        cache = _tmp_cache()
        cache.values(WEO, "INDICATOR")
        p = cache.path(WEO, "INDICATOR")
        entry = json.loads(p.read_text())
        entry["fetched_at"] = time.time() - 91 * 86400
        p.write_text(json.dumps(entry))
        self.assertFalse(cache.status(WEO, "INDICATOR")["fresh"])
        cache.values(WEO, "INDICATOR")
        self.assertTrue(cache.status(WEO, "INDICATOR")["fresh"])


class ResolveTests(unittest.TestCase):
    def test_expand_group(self):
        out = resolve.expand_group("advanced economies")
        self.assertTrue(out["matched"])
        self.assertIn("USA", out["iso3"])
        self.assertEqual(out["segment"], "+".join(out["iso3"]))

    def test_expand_group_ambiguous(self):
        out = resolve.expand_group("economies")  # Advanced Economies vs Emerging ... Economies
        self.assertFalse(out["matched"])
        self.assertTrue(out["ambiguous"])
        self.assertEqual({c["code"] for c in out["candidates"]}, {"G007", "G200"})

    def test_preview_wide_returns_head_and_total(self):
        out = resolve.preview(_weo_spec(stage="resolved", layout="wide"))
        self.assertEqual(out["returned_rows"], 5)
        self.assertEqual(out["total_rows"], 12)
        self.assertIn("USA.NGDP_RPCH.A", out["columns"])

    def test_preview_long_default(self):
        out = resolve.preview(_weo_spec(stage="resolved"))
        self.assertEqual(out["layout"], "long")
        self.assertIn("OBS_VALUE", out["columns"])
        self.assertEqual(out["total_rows"], 24)  # 2 series x 12 years

    def test_preview_zero_rows_has_note(self):
        spec = _weo_spec(stage="resolved")
        spec.dimensions[1].values = ["BOGUS"]
        out = resolve.preview(spec)
        self.assertEqual(out["total_rows"], 0)
        self.assertIn("Do not conclude", out["note"])


class RenderTests(unittest.TestCase):
    def test_all_three_languages_share_the_key(self):
        out = render(_weo_spec(stage="resolved"))
        for lang in ("python", "stata", "r"):
            self.assertIn("USA+JPN.NGDP_RPCH.A", out[lang])
            self.assertIn("2015", out[lang])
        self.assertIn("idata_utilities.PRIVATE = True", out["python"])
        self.assertIn("imf_datatools$get_idata_data", out["r"])
        self.assertIn("COUNTRY.INDICATOR.FREQUENCY", out["python"])

    def test_long_is_default_in_all_languages(self):
        out = render(_weo_spec(stage="resolved"))
        self.assertIn("longformat=True", out["python"])
        self.assertIn("idatause data, database(IMF.RES.WEO:WEO_LIVE) query(USA+JPN.NGDP_RPCH.A) tin(2015, 2026) panel(COUNTRY) clear", out["stata"])
        self.assertIn("longformat = TRUE", out["r"])

    def test_wide_switches_options(self):
        out = render(_weo_spec(stage="resolved", layout="wide"))
        self.assertIn("longformat=False", out["python"])
        self.assertNotIn("panel(", out["stata"])
        self.assertIn("longformat = FALSE", out["r"])

    def test_file_format_changes_save_line(self):
        out = render(_weo_spec(stage="resolved", file_format="dta"))
        self.assertIn("to_stata", out["python"])
        self.assertIn('save "', out["stata"])
        self.assertIn("haven::write_dta", out["r"])

    def test_render_refuses_incomplete_spec(self):
        res = envelope(render, spec=_weo_spec(stage="draft", end=None).to_dict())
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"]["type"], "invalid_call")


class SchemaTests(unittest.TestCase):
    def test_every_schema_has_an_implementation_entry(self):
        self.assertEqual(set(IMPLEMENTATIONS), set(TOOLS_BY_NAME))

    def test_harness_owned_tools_have_no_function_here(self):
        self.assertIsNone(implementation("idata_fetch"))
        self.assertIsNone(implementation("ask_user"))
        self.assertIsNotNone(implementation("render_code"))
        self.assertIsNotNone(implementation("idata_find_databases"))

    def test_openai_conversion(self):
        self.assertEqual(len(to_openai_tools()), len(TOOLS_BY_NAME))
        self.assertEqual(to_openai_tools()[0]["type"], "function")


if __name__ == "__main__":
    unittest.main()
