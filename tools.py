"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings


def _load_env() -> None:
    """Load .env, tolerating UTF-8 or UTF-16 (Windows editors save either)."""
    try:
        load_dotenv()
    except (UnicodeDecodeError, UnicodeError):
        # Some Windows editors write .env as UTF-16; retry with that encoding.
        load_dotenv(encoding="utf-16")


_load_env()

# All LLM tools use the same free Groq model (per the project spec).
MODEL = "llama-3.3-70b-versatile"

# Higher = better matches sort first.
_CONDITION_RANK = {"excellent": 2, "good": 1, "fair": 0}

# Pretty display names for the lowercase platform values stored in the data.
_PLATFORM_NAMES = {"depop": "Depop", "poshmark": "Poshmark", "thredup": "ThredUp"}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── shared helpers ────────────────────────────────────────────────────────────

def _tokenize(text) -> set:
    """Lowercase, strip punctuation, and split into a set of unique tokens."""
    return set(re.sub(r"[^a-z0-9]+", " ", str(text).lower()).split())


def _platform_name(platform) -> str:
    """Map a stored platform value (e.g. 'depop') to a display name ('Depop')."""
    return _PLATFORM_NAMES.get(str(platform or "").lower(), str(platform or "").title())


def _format_price(price) -> str:
    """Render a price like $24 or $29.99 (no trailing .0); fallback if missing."""
    if price is None:
        return "a great price"
    try:
        value = float(price)
    except (TypeError, ValueError):
        return f"${price}"
    return f"${int(value)}" if value.is_integer() else f"${value}"


def _format_item(item: dict) -> str:
    """Render the relevant fields of a listing dict for an LLM prompt."""
    parts = [
        f"Title: {item.get('title', '')}",
        f"Category: {item.get('category', '')}",
        f"Style tags: {', '.join(item.get('style_tags', []) or [])}",
        f"Colors: {', '.join(item.get('colors', []) or [])}",
        f"Condition: {item.get('condition', '')}",
        f"Price: ${item.get('price', '')}",
        f"Platform: {_platform_name(item.get('platform'))}",
    ]
    if item.get("brand"):
        parts.append(f"Brand: {item['brand']}")
    if item.get("description"):
        parts.append(f"Description: {item['description']}")
    return "\n".join(parts)


def _format_wardrobe(items: list) -> str:
    """Render wardrobe items as one labeled line each for an LLM prompt."""
    lines = []
    for it in items:
        bits = [it.get("name", "")]
        if it.get("category"):
            bits.append(f"({it['category']})")
        if it.get("colors"):
            bits.append("colors: " + ", ".join(it["colors"]))
        if it.get("style_tags"):
            bits.append("tags: " + ", ".join(it["style_tags"]))
        if it.get("notes"):
            bits.append(f"notes: {it['notes']}")
        lines.append("- " + " | ".join(bits))
    return "\n".join(lines)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive substring (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Scoring: each query token earns +1 if it appears anywhere in the listing's
    title/style_tags/description, +1 more if it is in the title, and +1 more if
    it is in a style tag. Listings scoring 0 are dropped. Ties break by condition
    (excellent > good > fair) then by lower price.
    """
    try:
        listings = load_listings()
    except Exception:
        return []

    try:
        query_tokens = _tokenize(description or "")
        if not query_tokens:
            return []

        norm_size = size.strip().lower() if size is not None else None

        scored = []
        for listing in listings:
            # Price filter (inclusive).
            price = listing.get("price")
            if max_price is not None and (price is None or price > max_price):
                continue

            # Size filter (case-insensitive substring).
            if norm_size is not None and norm_size not in str(listing.get("size", "")).lower():
                continue

            title_tokens = _tokenize(listing.get("title", ""))
            tag_tokens = _tokenize(" ".join(listing.get("style_tags", []) or []))
            desc_tokens = _tokenize(listing.get("description", ""))
            combined = title_tokens | tag_tokens | desc_tokens

            score = 0
            for token in query_tokens:
                if token in combined:
                    score += 1
                if token in title_tokens:
                    score += 1
                if token in tag_tokens:
                    score += 1

            if score > 0:
                scored.append((score, listing))

        scored.sort(
            key=lambda sl: (
                -sl[0],
                -_CONDITION_RANK.get(sl[1].get("condition"), -1),
                sl[1].get("price", float("inf")),
            )
        )
        return [listing for _, listing in scored]
    except Exception:
        return []


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handled gracefully.

    Returns:
        A non-empty string with outfit suggestions. If the wardrobe is empty,
        returns general styling advice for the item instead of crashing.
    """
    items = wardrobe.get("items", []) if isinstance(wardrobe, dict) else []
    item_block = _format_item(new_item)
    client = _get_groq_client()

    if not items:
        system = (
            "You are a practical personal stylist. The user has not logged a "
            "wardrobe yet, so give general styling guidance for the item: what "
            "categories, colors, and silhouettes pair well, the vibe and "
            "occasions it suits, and 1-2 example outfit directions described "
            "generically. Do not reference specific pieces the user owns."
        )
        user = (
            "The user is considering this thrifted find but has no wardrobe "
            f"logged yet.\n\nItem:\n{item_block}\n\n"
            "Give concise, actionable general styling advice."
        )
    else:
        system = (
            "You are a practical personal stylist. Build real, wearable outfits "
            "using ONLY the new item and pieces from the user's wardrobe. Refer "
            "to wardrobe pieces by their exact names. Do not invent items the "
            "user does not own. Suggest exactly 1-2 complete outfits, each with "
            "a one-line reason it works. Keep it tight, no preamble."
        )
        user = (
            f"New item:\n{item_block}\n\n"
            f"User's wardrobe:\n{_format_wardrobe(items)}\n\n"
            "Suggest 1-2 complete outfits that pair the new item with named "
            "pieces from the wardrobe."
        )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption. If outfit
        is empty or missing, returns a descriptive error message string instead
        of raising an exception.
    """
    if not outfit or not outfit.strip():
        return (
            "Couldn't create a fit card: no outfit description was provided. "
            "Run suggest_outfit first to generate an outfit, then try again."
        )

    client = _get_groq_client()
    title = new_item.get("title", "this piece")
    price_str = _format_price(new_item.get("price"))
    platform = _platform_name(new_item.get("platform"))

    system = (
        "You write casual, authentic OOTD captions for thrifted finds, the kind "
        "a real person posts on Instagram or TikTok. Sound personal and "
        "spontaneous, NOT like a product description or ad. Rules: 2-4 sentences; "
        "mention the item name, its price, and the platform exactly once each, "
        "woven in naturally; capture the specific vibe of the look; no salesy "
        "language, no hashtag spam."
    )
    user = (
        f"Item name: {title}\nPrice: {price_str}\nPlatform: {platform}\n"
        f"Colors: {', '.join(new_item.get('colors', []) or [])}\n"
        f"Style tags: {', '.join(new_item.get('style_tags', []) or [])}\n\n"
        f"Outfit:\n{outfit}\n\n"
        "Write the caption."
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=1.0,
    )
    return response.choices[0].message.content.strip()
