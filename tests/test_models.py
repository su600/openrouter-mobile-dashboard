#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旗舰模型筛选逻辑测试（纯函数，无需网络）。"""
import unittest

import openrouter_api as api


def M(model_id, name, prompt, completion, created=0, ctx=1000, intelligence_index=None):
    return {
        "id": model_id,
        "name": name,
        "pricing": {"prompt": prompt, "completion": completion},
        "context_length": ctx,
        "benchmarks": {"artificial_analysis": {"intelligence_index": intelligence_index}},
        "created": created,
    }


class TestVersionAndSeries(unittest.TestCase):
    def test_major_version(self):
        self.assertEqual(api._model_major_version("openai/gpt-6-astra", "gpt"), 6)
        self.assertEqual(api._model_major_version("openai/gpt-5.4", "gpt"), 5)
        self.assertEqual(api._model_major_version("anthropic/claude-opus-5.5", "claude"), 5)
        self.assertIsNone(api._model_major_version("openai/gpt-oss-120b", "gpt"))
        self.assertIsNone(api._model_major_version("anthropic/claude-3-haiku", "claude"))

    def test_series(self):
        self.assertEqual(api._model_series("openai/gpt-6-astra", "gpt"), "astra")
        self.assertEqual(api._model_series("openai/gpt-6-sol", "gpt"), "sol")
        self.assertEqual(api._model_series("anthropic/claude-opus-5.5", "claude"), "opus")
        self.assertEqual(api._model_series("anthropic/claude-sonnet-5", "claude"), "sonnet")

    def test_price_per_million(self):
        self.assertEqual(api._price_per_million("0.000001"), 1.0)
        self.assertEqual(api._price_per_million("0.0000003"), 0.3)
        self.assertIsNone(api._price_per_million(None))
        self.assertIsNone(api._price_per_million("abc"))


class TestBuildFlagshipFamilies(unittest.TestCase):
    def setUp(self):
        self.models = [
            # GPT-6（最新代）：保留基础版，排除 Pro / batch / 别名
            M("openai/gpt-6-astra", "OpenAI: GPT-6 Astra", "1e-5", "5e-5", created=10, intelligence_index=52.7),
            M("openai/gpt-6-astra-pro", "OpenAI: GPT-6 Astra Pro", "1e-5", "5e-5", created=11),
            M("openai/gpt-6-sol", "OpenAI: GPT-6 Sol", "2e-6", "1e-5", created=12),
            M("openai/gpt-6-sol:batch", "OpenAI: GPT-6 Sol (batch)", "1e-6", "5e-6", created=12),
            M("~openai/gpt-astra-latest", "OpenAI: GPT Astra Latest", "1e-5", "5e-5", created=99),
            M("openai/gpt-5.4", "OpenAI: GPT-5.4", "2.5e-6", "1.5e-5", created=1),  # 非最新代，排除
            # Claude：最新代 v5，同系列只留最新版本；haiku 4.5 属 v4，排除
            M("anthropic/claude-opus-5", "Anthropic: Claude Opus 5", "5e-6", "2.5e-5", created=20),
            M("anthropic/claude-opus-5.5", "Anthropic: Claude Opus 5.5", "4e-6", "2e-5", created=21),
            M("anthropic/claude-sonnet-5", "Anthropic: Claude Sonnet 5", "2e-6", "1e-5", created=22),
            M("anthropic/claude-haiku-4.5", "Anthropic: Claude Haiku 4.5", "1e-6", "5e-6", created=5),
        ]

    def test_families_shape(self):
        fams = {f["key"]: f for f in api.build_flagship_families(self.models)}
        self.assertEqual(set(fams), {"gpt", "claude"})

    def test_gpt_latest_gen_and_no_pro(self):
        gpt = {f["key"]: f for f in api.build_flagship_families(self.models)}["gpt"]
        self.assertEqual(gpt["generation"], 6)
        self.assertEqual([m["name"] for m in gpt["models"]], ["GPT-6 Astra", "GPT-6 Sol"])
        self.assertEqual(gpt["models"][0]["input"], 10.0)
        self.assertEqual(gpt["models"][0]["output"], 50.0)

    def test_claude_latest_series_only(self):
        claude = {f["key"]: f for f in api.build_flagship_families(self.models)}["claude"]
        self.assertEqual(claude["generation"], 5)
        # Opus 5 与 5.5 只留 5.5；sonnet 保留；haiku(v4) 排除
        self.assertEqual(
            [m["name"] for m in claude["models"]],
            ["Claude Opus 5.5", "Claude Sonnet 5"],
        )

    def test_intelligence_index_is_included_and_missing_value_is_none(self):
        gpt = {f["key"]: f for f in api.build_flagship_families(self.models)}["gpt"]
        scores = {model["id"]: model["intelligence_index"] for model in gpt["models"]}
        self.assertEqual(scores["openai/gpt-6-astra"], 52.7)
        self.assertIsNone(scores["openai/gpt-6-sol"])

    def test_empty_models(self):
        self.assertEqual(api.build_flagship_families([]), [])


class TestBuildLatestModels(unittest.TestCase):
    def alias(self, alias_id, slug, name):
        return {"id": alias_id, "name": name, "alias_target": {"slug": slug, "name": name}}

    def test_resolves_all_six_tiers(self):
        models = [
            self.alias("~anthropic/claude-opus-latest", "anthropic/claude-opus-5.5", "Anthropic: Claude Opus 5.5"),
            self.alias("~anthropic/claude-sonnet-latest", "anthropic/claude-sonnet-5.5", "Anthropic: Claude Sonnet Latest"),
            self.alias("~anthropic/claude-haiku-latest", "anthropic/claude-haiku-5.5", "Anthropic: Claude Haiku Latest"),
            self.alias("~openai/gpt-astra-latest", "openai/gpt-6-astra", "OpenAI: GPT-6 Astra"),
            self.alias("~openai/gpt-sol-latest", "openai/gpt-6.1-sol", "OpenAI: GPT Sol Latest"),
            self.alias("~openai/gpt-luna-latest", "openai/gpt-6-luna", "OpenAI: GPT Luna Latest"),
        ]
        rows = api.build_latest_models(models)
        self.assertEqual([r["tier"] for r in rows], ["Opus", "Sonnet", "Haiku", "Astra", "Sol", "Luna"])
        self.assertTrue(all(r["found"] for r in rows))
        self.assertEqual(rows[0]["resolved_id"], "anthropic/claude-opus-5.5")
        self.assertEqual(rows[0]["resolved_name"], "Claude Opus 5.5")
        self.assertEqual(rows[3]["resolved_id"], "openai/gpt-6-astra")
        self.assertEqual(rows[3]["resolved_name"], "GPT-6 Astra")

    def test_missing_alias_is_reported_not_found(self):
        rows = api.build_latest_models([])
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(not r["found"] and r["resolved_id"] is None for r in rows))

    def test_non_dict_entries_are_ignored(self):
        rows = api.build_latest_models([None, "x", self.alias("~openai/gpt-luna-latest", "openai/gpt-6-luna", "OpenAI: GPT Luna Latest")])
        luna = [r for r in rows if r["tier"] == "Luna"][0]
        self.assertTrue(luna["found"])


if __name__ == "__main__":
    unittest.main()