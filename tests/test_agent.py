"""
Agent-level failure-mode tests (Milestone 5).

These exercise the whole planning loop, not just the tools, to prove the agent
recovers gracefully from each failure mode instead of crashing.

The no-results branch test needs no API key (search returns [] before any LLM
call). The happy-path and empty-wardrobe tests call the LLM, so they skip when
GROQ_API_KEY is not set.
"""

import os

import pytest

from agent import run_agent
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

HAS_KEY = bool(os.environ.get("GROQ_API_KEY"))
requires_key = pytest.mark.skipif(not HAS_KEY, reason="GROQ_API_KEY not set")


# ── failure mode 1: search returns nothing (keyless) ──────────────────────────

def test_no_results_sets_error_and_skips_llm_tools():
    session = run_agent("designer ballgown size XXS under $5", get_example_wardrobe())
    # A specific, actionable error is set...
    assert session["error"]
    assert "designer ballgown" in session["error"]
    assert session["search_results"] == []
    # ...and the LLM tools were never reached.
    assert session["selected_item"] is None
    assert session["outfit_suggestion"] is None
    assert session["fit_card"] is None


def test_no_results_does_not_raise_for_various_impossible_queries():
    for q in ["xyzzy nonsense item", "platinum spacesuit size 99 under $1"]:
        session = run_agent(q, get_example_wardrobe())
        assert session["error"]
        assert session["fit_card"] is None


# ── adaptiveness: happy path vs failure differ (happy needs a key) ─────────────

@requires_key
def test_happy_path_runs_all_three_and_flows_state():
    session = run_agent("vintage graphic tee under $30", get_example_wardrobe())
    assert session["error"] is None
    assert session["selected_item"]["id"] == "lst_006"
    assert session["outfit_suggestion"] and session["fit_card"]
    # State flows with no re-entry: the selected item IS the search top result,
    # i.e. the same object handed to the downstream tools.
    assert session["selected_item"] is session["search_results"][0]


# ── failure mode 2: empty wardrobe still produces a result (needs a key) ──────

@requires_key
def test_empty_wardrobe_falls_back_to_general_advice():
    session = run_agent("vintage graphic tee under $30", get_empty_wardrobe())
    assert session["error"] is None
    # suggest_outfit degrades to general advice instead of crashing / returning "".
    assert session["outfit_suggestion"].strip()
    assert session["fit_card"].strip()
