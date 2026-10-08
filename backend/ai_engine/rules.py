"""Explainable rule-based AI decision support for condition assessments.

This is NOT machine learning: there is no historical Yellow dataset to train
on. It is a deterministic, versioned rule set. The same inputs always give the
same recommendation, score, confidence and reasons.

Every weight and threshold lives in this module as a named constant, so the
rules can be reviewed, documented (docs/architecture.md section 7) and tested
in one place. Changing any of them means bumping RULE_VERSION.

The engine only RECOMMENDS. It has no access to the device and never changes
its status; a permitted human makes the final decision.
"""

from dataclasses import dataclass, field

RULE_VERSION = "rules-v1.0"

# --- Recommendations ---------------------------------------------------------

REFURBISH = "REFURBISH"
READY_FOR_DISPOSITION = "READY_FOR_DISPOSITION"
UNABLE_TO_REPAIR = "UNABLE_TO_REPAIR"

# --- Score weights (points; a perfect device scores 100) ----------------------

FUNCTIONAL_POINTS = {"FULLY_FUNCTIONAL": 30, "PARTIALLY_FUNCTIONAL": 15, "NON_FUNCTIONAL": 0}
PHYSICAL_POINTS = {"EXCELLENT": 20, "GOOD": 16, "FAIR": 10, "POOR": 4, "CRITICAL": 0}
SCREEN_POINTS = {"INTACT": 15, "MINOR_DAMAGE": 10, "MAJOR_DAMAGE": 4, "BROKEN": 0}
BATTERY_POINTS = {"EXCELLENT": 15, "GOOD": 12, "FAIR": 7, "POOR": 3, "FAILED": 0}
COSMETIC_POINTS = {"EXCELLENT": 10, "GOOD": 8, "FAIR": 5, "POOR": 2}
ACCESSORIES_POINTS = {"COMPLETE": 5, "PARTIAL": 3, "NONE": 0}

# Economics: up to 5 points when repair is cheap relative to the device's value.
ECONOMY_POINTS_LOW_RATIO = 5      # repair cost <= LOW_REPAIR_RATIO of market value
ECONOMY_POINTS_MEDIUM_RATIO = 2   # repair cost <= MEDIUM_REPAIR_RATIO of market value
LOW_REPAIR_RATIO = 0.25
MEDIUM_REPAIR_RATIO = 0.50

# Each recorded defect deducts points, up to a cap.
DEFECT_PENALTY = 3
MAX_DEFECT_PENALTY = 15

# --- Decision thresholds -----------------------------------------------------

# Repair costing more than this share of the market value is uneconomic.
MAX_REPAIR_TO_VALUE_RATIO = 0.60
# A non-functional device scoring below this is treated as beyond repair.
UNREPAIRABLE_SCORE = 35
# Minimum score for a device to go straight to disposition without refurbishment.
READY_MIN_SCORE = 75
# Repair cost share still acceptable for "ready as-is" (e.g. cleaning only).
READY_MAX_REPAIR_RATIO = 0.10
# Findings that always need refurbishment work before disposition.
REPAIR_NEEDED_SCREEN = {"MAJOR_DAMAGE", "BROKEN"}
REPAIR_NEEDED_BATTERY = {"POOR", "FAILED"}

# --- Confidence --------------------------------------------------------------
# Confidence expresses how far the inputs sit from the nearest threshold that
# would change the recommendation. It is a rule-based certainty indicator, not
# a statistical probability.
CONFIDENCE_BASE = 0.60
CONFIDENCE_PER_MARGIN = 1.5
CONFIDENCE_MIN = 0.55
CONFIDENCE_MAX = 0.95
CONFIDENCE_HARD_STOP = 0.95  # unambiguous rules, e.g. critical physical damage

LABELS = {
    "FULLY_FUNCTIONAL": "fully functional",
    "PARTIALLY_FUNCTIONAL": "partially functional",
    "NON_FUNCTIONAL": "non-functional",
    "INTACT": "intact",
    "MINOR_DAMAGE": "minor damage",
    "MAJOR_DAMAGE": "major damage",
    "BROKEN": "broken",
    "EXCELLENT": "excellent",
    "GOOD": "good",
    "FAIR": "fair",
    "POOR": "poor",
    "CRITICAL": "critical",
    "FAILED": "failed",
    "COMPLETE": "complete",
    "PARTIAL": "partial",
    "NONE": "missing",
}


@dataclass(frozen=True)
class AssessmentInputs:
    functional_status: str
    physical_condition: str
    screen_condition: str
    battery_condition: str
    cosmetic_condition: str
    accessories_condition: str
    defects: tuple
    estimated_repair_cost_rwf: int
    estimated_market_value_rwf: int


@dataclass(frozen=True)
class Recommendation:
    recommendation: str
    score: int
    confidence: float
    reasons: list = field(default_factory=list)
    factors: dict = field(default_factory=dict)
    rule: str = ""
    rule_version: str = RULE_VERSION


def rwf(amount):
    return f"{amount:,} RWF"


def _confidence(margin):
    value = CONFIDENCE_BASE + CONFIDENCE_PER_MARGIN * margin
    return round(min(CONFIDENCE_MAX, max(CONFIDENCE_MIN, value)), 2)


def score_assessment(inputs):
    """Return (score 0-100, factor points, repair-to-value ratio)."""
    ratio = inputs.estimated_repair_cost_rwf / inputs.estimated_market_value_rwf
    if ratio <= LOW_REPAIR_RATIO:
        economy = ECONOMY_POINTS_LOW_RATIO
    elif ratio <= MEDIUM_REPAIR_RATIO:
        economy = ECONOMY_POINTS_MEDIUM_RATIO
    else:
        economy = 0

    factors = {
        "functionality": FUNCTIONAL_POINTS[inputs.functional_status],
        "physical": PHYSICAL_POINTS[inputs.physical_condition],
        "screen": SCREEN_POINTS[inputs.screen_condition],
        "battery": BATTERY_POINTS[inputs.battery_condition],
        "cosmetic": COSMETIC_POINTS[inputs.cosmetic_condition],
        "accessories": ACCESSORIES_POINTS[inputs.accessories_condition],
        "repair_economics": economy,
        "defects": -min(MAX_DEFECT_PENALTY, DEFECT_PENALTY * len(inputs.defects)),
    }
    score = max(0, min(100, sum(factors.values())))
    return score, factors, ratio


def _finding_reasons(inputs, ratio):
    reasons = [
        f"Device is {LABELS[inputs.functional_status]}.",
        f"Physical condition is {LABELS[inputs.physical_condition]}; cosmetic condition is "
        f"{LABELS[inputs.cosmetic_condition]}.",
        f"Screen: {LABELS[inputs.screen_condition]}.",
        f"Battery: {LABELS[inputs.battery_condition]}.",
        f"Accessories: {LABELS[inputs.accessories_condition]}.",
    ]
    if inputs.defects:
        reasons.append(f"{len(inputs.defects)} specific defect(s) recorded.")
    reasons.append(
        f"Estimated repair cost is {rwf(inputs.estimated_repair_cost_rwf)}; estimated market value is "
        f"{rwf(inputs.estimated_market_value_rwf)} ({ratio:.0%} of value)."
    )
    return reasons


def evaluate(inputs):
    """Apply the rules, in order, and explain the result."""
    score, factors, ratio = score_assessment(inputs)
    reasons = _finding_reasons(inputs, ratio)
    needs_repair = (
        inputs.functional_status != "FULLY_FUNCTIONAL"
        or inputs.screen_condition in REPAIR_NEEDED_SCREEN
        or inputs.battery_condition in REPAIR_NEEDED_BATTERY
        or bool(inputs.defects)
        or ratio > READY_MAX_REPAIR_RATIO
    )

    # Rule 1: critical physical damage is beyond economic repair.
    if inputs.physical_condition == "CRITICAL":
        reasons.append("Rule: critical physical damage means the device cannot be economically repaired.")
        return Recommendation(UNABLE_TO_REPAIR, score, CONFIDENCE_HARD_STOP, reasons, factors, "critical_damage")

    # Rule 2: repair costs too much compared with what the device is worth.
    if ratio > MAX_REPAIR_TO_VALUE_RATIO:
        reasons.append(
            f"Rule: repair would cost more than {MAX_REPAIR_TO_VALUE_RATIO:.0%} of the market value, "
            "so it is uneconomic."
        )
        margin = ratio - MAX_REPAIR_TO_VALUE_RATIO
        return Recommendation(UNABLE_TO_REPAIR, score, _confidence(margin), reasons, factors, "uneconomic_repair")

    # Rule 3: a non-functional device in poor overall condition.
    if inputs.functional_status == "NON_FUNCTIONAL" and score < UNREPAIRABLE_SCORE:
        reasons.append(
            f"Rule: the device is non-functional and its condition score ({score}) is below "
            f"{UNREPAIRABLE_SCORE}, so repair is unlikely to succeed."
        )
        margin = (UNREPAIRABLE_SCORE - score) / 100
        return Recommendation(UNABLE_TO_REPAIR, score, _confidence(margin), reasons, factors, "non_functional_low_score")

    # Rule 4: fully working, good condition, nothing to fix -> ready as-is.
    if not needs_repair and score >= READY_MIN_SCORE:
        reasons.append(
            f"Rule: the device works, needs no repair and scores {score} (at least {READY_MIN_SCORE}), "
            "so it can go to reallocation or resale as-is."
        )
        margin = (score - READY_MIN_SCORE) / 100
        return Recommendation(READY_FOR_DISPOSITION, score, _confidence(margin), reasons, factors, "ready_as_is")

    # Rule 5: repairable, and repair is economic -> refurbish.
    margins = [MAX_REPAIR_TO_VALUE_RATIO - ratio]
    if inputs.functional_status == "NON_FUNCTIONAL":
        margins.append((score - UNREPAIRABLE_SCORE) / 100)
    if needs_repair:
        reasons.append(
            f"Rule: the device has repairable issues and the repair cost is within {MAX_REPAIR_TO_VALUE_RATIO:.0%} "
            "of the market value, so refurbishment is worthwhile."
        )
        rule = "economic_repair"
    else:
        reasons.append(
            f"Rule: the device works but its condition score ({score}) is below {READY_MIN_SCORE}, so "
            "refurbishment is recommended before reallocation or resale."
        )
        margins.append((READY_MIN_SCORE - score) / 100)
        rule = "below_ready_score"
    return Recommendation(REFURBISH, score, _confidence(min(margins)), reasons, factors, rule)
