"""Literal rule matching and specificity scoring (3.2 plan, section 3, stages 1, 4, 5 and 7)."""
from __future__ import annotations

from dataclasses import dataclass

from app.definitions.contract import MatchRule
from app.engine.normalizer import contains_term


@dataclass(frozen=True, order=True)
class Specificity:
    """Higher is more specific. Compared field by field, in this order."""

    exact: int  # 1 when the whole message equals one of the rule's exact phrases
    groups: int  # match groups the rule requires
    requirements: int  # requirements the rule's intent satisfied
    terms: int  # distinct terms that matched
    longest: int  # length of the longest matched term


def exact_match(rule: MatchRule, text: str) -> bool:
    return text in rule.exact


def match_rule(rule: MatchRule, text: str) -> Specificity | None:
    """How specifically `rule` matches `text`, or None when it does not match."""
    if exact_match(rule, text):
        return Specificity(1, len(rule.match), 0, 1, len(text))
    if not rule.match or any(contains_term(text, term) for term in rule.exclude):
        return None
    matched: set[str] = set()
    for group in rule.match:
        hits = [term for term in group if contains_term(text, term)]
        if not hits:
            return None
        matched.update(hits)
    return Specificity(0, len(rule.match), 0, len(matched), max(len(term) for term in matched))


def rule_terms(rules: list[MatchRule]) -> set[str]:
    """Every literal a set of rules can match, used as known words by the normalizer."""
    terms: set[str] = set()
    for rule in rules:
        terms.update(rule.exact)
        terms.update(rule.exclude)
        for group in rule.match:
            terms.update(group)
    return terms
