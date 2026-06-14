"""
Tests for the three FitFindr tools.

Run with:  pytest tests/

Pure-Python search tests and the create_fit_card empty-outfit guard run with no
API key. Tests that actually call the LLM are skipped automatically when
GROQ_API_KEY is not set, so the suite stays green without a key.
"""

import os

import pytest

# Importing tools loads the .env (tolerating UTF-8/UTF-16) before we read the key.
from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

HAS_KEY = bool(os.environ.get("GROQ_API_KEY"))
requires_key = pytest.mark.skipif(not HAS_KEY, reason="GROQ_API_KEY not set")


# ── search_listings (no API needed) ───────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    # Every element is a full listing dict.
    assert all("id" in r and "price" in r for r in results)


def test_search_empty_results():
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []  # empty list, no exception


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter_substring():
    # "m" should match sizes like "M", "S/M", "M/L" but the function must not crash.
    results = search_listings("trousers", size="M", max_price=None)
    assert all("m" in str(item["size"]).lower() for item in results)


def test_search_ranking_top_match():
    # Spec: for "vintage graphic tee" under $30 the strongest match is lst_006.
    results = search_listings("vintage graphic tee", size=None, max_price=30)
    assert results, "expected at least one match"
    assert results[0]["id"] == "lst_006"
    assert results[0]["price"] <= 30


def test_search_empty_description_returns_empty():
    assert search_listings("", size=None, max_price=None) == []


# ── create_fit_card guard (no API needed) ─────────────────────────────────────

def test_create_fit_card_empty_outfit_returns_message():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = create_fit_card("", item)
    assert isinstance(result, str)
    assert result.strip() != ""
    # It is the guard message, not a generated caption.
    assert "fit card" in result.lower()


def test_create_fit_card_whitespace_outfit_returns_message():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = create_fit_card("   \n  ", item)
    assert isinstance(result, str)
    assert result.strip() != ""


# ── LLM-backed tests (skipped without GROQ_API_KEY) ───────────────────────────

@requires_key
def test_suggest_outfit_with_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_example_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""


@requires_key
def test_suggest_outfit_empty_wardrobe():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert result.strip() != ""  # general advice, not empty / not a crash


@requires_key
def test_create_fit_card_varies():
    item = search_listings("vintage graphic tee", size=None, max_price=50)[0]
    outfit = "Pair the tee with baggy jeans and chunky sneakers, denim jacket on top."
    a = create_fit_card(outfit, item)
    b = create_fit_card(outfit, item)
    assert a.strip() and b.strip()
    assert a != b  # higher temperature should vary the caption
