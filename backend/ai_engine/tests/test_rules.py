"""Unit tests for the rule engine: no database, just the documented rules."""

import itertools
from dataclasses import replace

from django.test import SimpleTestCase

from ai_engine import rules
from ai_engine.rules import AssessmentInputs, evaluate, score_assessment

PERFECT = AssessmentInputs(
    functional_status="FULLY_FUNCTIONAL",
    physical_condition="EXCELLENT",
    screen_condition="INTACT",
    battery_condition="EXCELLENT",
    cosmetic_condition="EXCELLENT",
    accessories_condition="COMPLETE",
    defects=(),
    estimated_repair_cost_rwf=0,
    estimated_market_value_rwf=120_000,
)

# The worked example from the project brief: partially working, major screen damage, cheap repair.
SCREEN_DAMAGE = AssessmentInputs(
    functional_status="PARTIALLY_FUNCTIONAL",
    physical_condition="GOOD",
    screen_condition="MAJOR_DAMAGE",
    battery_condition="FAIR",
    cosmetic_condition="GOOD",
    accessories_condition="PARTIAL",
    defects=(),
    estimated_repair_cost_rwf=18_000,
    estimated_market_value_rwf=85_000,
)


class ScoringTests(SimpleTestCase):
    def test_perfect_device_scores_100(self):
        score, factors, ratio = score_assessment(PERFECT)
        self.assertEqual(score, 100)
        self.assertEqual(ratio, 0)
        self.assertEqual(sum(factors.values()), 100)

    def test_worked_example_score(self):
        score, factors, _ = score_assessment(SCREEN_DAMAGE)
        # 15 functional + 16 physical + 4 screen + 7 battery + 8 cosmetic + 3 accessories + 5 economics
        self.assertEqual(score, 58)
        self.assertEqual(factors["screen"], 4)
        self.assertEqual(factors["repair_economics"], rules.ECONOMY_POINTS_LOW_RATIO)

    def test_defect_penalty_is_capped(self):
        many = replace(PERFECT, defects=tuple(f"D{i}" for i in range(10)))
        _, factors, _ = score_assessment(many)
        self.assertEqual(factors["defects"], -rules.MAX_DEFECT_PENALTY)

    def test_economics_points_follow_ratio_bands(self):
        for cost, expected in ((30_000, 5), (60_000, 2), (70_000, 0)):  # value 120,000
            with self.subTest(cost=cost):
                _, factors, _ = score_assessment(replace(PERFECT, estimated_repair_cost_rwf=cost))
                self.assertEqual(factors["repair_economics"], expected)

    def test_all_inputs_stay_in_range(self):
        """Every combination of controlled choices gives a valid, bounded result."""
        for combo in itertools.product(
            rules.FUNCTIONAL_POINTS,
            rules.PHYSICAL_POINTS,
            rules.SCREEN_POINTS,
            rules.BATTERY_POINTS,
            rules.COSMETIC_POINTS,
            rules.ACCESSORIES_POINTS,
            ((), ("CAMERA_FAULT",)),
            (0, 50_000, 100_000),
        ):
            inputs = AssessmentInputs(*combo[:7], estimated_repair_cost_rwf=combo[7], estimated_market_value_rwf=100_000)
            result = evaluate(inputs)
            self.assertTrue(0 <= result.score <= 100, combo)
            self.assertTrue(rules.CONFIDENCE_MIN <= result.confidence <= rules.CONFIDENCE_MAX, combo)
            self.assertIn(result.recommendation, (rules.REFURBISH, rules.READY_FOR_DISPOSITION, rules.UNABLE_TO_REPAIR))
            self.assertTrue(result.reasons)


class RecommendationRuleTests(SimpleTestCase):
    def test_perfect_device_is_ready_for_disposition(self):
        result = evaluate(PERFECT)
        self.assertEqual(result.recommendation, rules.READY_FOR_DISPOSITION)
        self.assertEqual(result.rule, "ready_as_is")
        self.assertEqual(result.confidence, rules.CONFIDENCE_MAX)

    def test_worked_example_is_refurbish(self):
        result = evaluate(SCREEN_DAMAGE)
        self.assertEqual(result.recommendation, rules.REFURBISH)
        self.assertEqual(result.rule, "economic_repair")

    def test_critical_physical_damage_is_unable_to_repair(self):
        result = evaluate(replace(PERFECT, physical_condition="CRITICAL"))
        self.assertEqual(result.recommendation, rules.UNABLE_TO_REPAIR)
        self.assertEqual(result.rule, "critical_damage")
        self.assertEqual(result.confidence, rules.CONFIDENCE_HARD_STOP)

    def test_uneconomic_repair_is_unable_to_repair(self):
        result = evaluate(replace(SCREEN_DAMAGE, estimated_repair_cost_rwf=70_000))  # 82% of value
        self.assertEqual(result.recommendation, rules.UNABLE_TO_REPAIR)
        self.assertEqual(result.rule, "uneconomic_repair")

    def test_repair_exactly_at_threshold_is_still_economic(self):
        result = evaluate(replace(SCREEN_DAMAGE, estimated_repair_cost_rwf=51_000))  # exactly 60%
        self.assertEqual(result.recommendation, rules.REFURBISH)

    def test_non_functional_wreck_is_unable_to_repair(self):
        wreck = replace(
            SCREEN_DAMAGE,
            functional_status="NON_FUNCTIONAL",
            physical_condition="POOR",
            screen_condition="BROKEN",
            battery_condition="FAILED",
            cosmetic_condition="POOR",
            accessories_condition="NONE",
        )
        result = evaluate(wreck)
        self.assertEqual(result.recommendation, rules.UNABLE_TO_REPAIR)
        self.assertEqual(result.rule, "non_functional_low_score")

    def test_non_functional_but_otherwise_good_is_refurbish(self):
        result = evaluate(replace(PERFECT, functional_status="NON_FUNCTIONAL", estimated_repair_cost_rwf=20_000))
        self.assertEqual(result.recommendation, rules.REFURBISH)

    def test_working_device_below_ready_score_is_refurbish(self):
        tired = replace(
            PERFECT,
            physical_condition="FAIR",
            screen_condition="MINOR_DAMAGE",
            battery_condition="FAIR",
            cosmetic_condition="POOR",
            accessories_condition="NONE",
        )
        result = evaluate(tired)
        self.assertLess(result.score, rules.READY_MIN_SCORE)
        self.assertEqual(result.recommendation, rules.REFURBISH)
        self.assertEqual(result.rule, "below_ready_score")
        self.assertIn("below", result.reasons[-1])

    def test_any_defect_needs_refurbishment(self):
        result = evaluate(replace(PERFECT, defects=("CHARGING_PORT_FAULT",)))
        self.assertEqual(result.recommendation, rules.REFURBISH)

    def test_critical_rule_takes_priority_over_economics(self):
        result = evaluate(replace(PERFECT, physical_condition="CRITICAL", estimated_repair_cost_rwf=100_000))
        self.assertEqual(result.rule, "critical_damage")


class ExplanationTests(SimpleTestCase):
    def test_result_is_deterministic(self):
        self.assertEqual(evaluate(SCREEN_DAMAGE), evaluate(SCREEN_DAMAGE))

    def test_reasons_explain_inputs_money_and_rule(self):
        reasons = evaluate(SCREEN_DAMAGE).reasons
        text = " ".join(reasons)
        self.assertIn("partially functional", text)
        self.assertIn("major damage", text)
        self.assertIn("18,000 RWF", text)
        self.assertIn("85,000 RWF", text)
        self.assertTrue(reasons[-1].startswith("Rule:"))

    def test_rule_version_is_reported(self):
        self.assertEqual(evaluate(PERFECT).rule_version, rules.RULE_VERSION)
