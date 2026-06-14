# FitFindr

FitFindr is a multi tool AI agent for thrifting. you type what ur after in plain english (like "vintage graphic tee under $30") and it runs 3 tools in order: `search_listings` digs thru the mock secondhand listings and ranks the matches, `suggest_outfit` takes the top find + ur existing wardrobe and builds actual outfits, and `create_fit_card` writes a short shareable OOTD caption for it. the whole point isnt the search, its the agent part: a planning loop that decides which tool to call based on what came back, passes state between the tools so you never re enter anything, and fails gracefully when a tool comes back w nothing (eg an impossible query stops after the search and tells you what to change instead of crashing or styling an item that doesnt exist).

## what a run looks like

1. you type "vintage graphic tee under $30" and pick a wardrobe.
2. the agent parses that into description "vintage graphic tee", size None, max_price 30.0.
3. `search_listings` ranks the matches and the top one is lst_006 "Graphic Tee, 2003 Tour Bootleg Style" ($24, depop, good).
4. `suggest_outfit` pairs it w real pieces from the example wardrobe (baggy dark wash jeans + chunky white sneakers, denim jacket on top).
5. `create_fit_card` turns that into a caption you could actually post.
6. if the query was impossible (like "designer ballgown size XXS under $5") it stops after step 3, shows a specific error, and never calls the other 2 tools.

## setup

```bash
python -m venv .venv
.venv\Scripts\activate          # windows
# source .venv/bin/activate     # mac/linux
pip install -r requirements.txt
```

put a free groq key (from console.groq.com) in a `.env` file in the repo root:
```
GROQ_API_KEY=your_key_here
```
the env loader handles both utf-8 and utf-16 .env files (windows editors save either), so you dont have to worry about the encoding.

## run it

```bash
python app.py        # launches the gradio ui, open the localhost url it prints
python agent.py      # cli: runs a happy query + the no-results branch
pytest tests/        # runs the tool + agent tests
```

the search and guard tests run w no key. the tests that call the LLM skip automatically if `GROQ_API_KEY` isnt set, so `pytest tests/` stays green either way.

## the tools

all 3 live in `tools.py`. signatures match exactly whats documented here.

### `search_listings(description: str, size: str | None = None, max_price: float | None = None) -> list[dict]`
- **what:** pure python keyword search over the 40 listings, no LLM.
- **inputs:** `description` (str) keywords like "vintage graphic tee"; `size` (str | None) case insensitive substring filter so "m" matches "M"/"S/M"/"M/L"; `max_price` (float | None) inclusive price ceiling.
- **returns:** a `list[dict]` sorted best match first. each element is the full listing dict (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`). only listings scoring > 0 are included. returns `[]` when nothing matches.
- **purpose:** find the candidate item to style.

scoring: each query token earns +1 if it shows up anywhere in title/style_tags/description, +1 more if its in the title, +1 more if its in a tag. drop the 0s, sort by score then condition (excellent > good > fair) then lower price.

### `suggest_outfit(new_item: dict, wardrobe: dict) -> str`
- **what:** calls groq `llama-3.3-70b-versatile` to build 1 to 2 outfits.
- **inputs:** `new_item` (dict) a listing dict from search (its name field is `title`); `wardrobe` (dict) w an `items` list, each item has `id`, `name`, `category`, `colors`, `style_tags`, optional `notes`.
- **returns:** a non empty `str`. populated wardrobe = specific combos naming real owned pieces; empty wardrobe = general styling advice.
- **purpose:** turn a found item into wearable outfit ideas.

### `create_fit_card(outfit: str, new_item: dict) -> str`
- **what:** calls groq (temp 1.0 so it varies) to write a 2 to 4 sentence OOTD caption.
- **inputs:** `outfit` (str) the suggestion text; `new_item` (dict) the listing (uses `title`, `price`, `platform`, colors, tags).
- **returns:** a casual caption `str` that names the item, price ("$24" not "$24.0"), and platform once each. if `outfit` is empty/whitespace it returns a descriptive error string.
- **purpose:** make the find shareable.

## how the planning loop works

`run_agent(query, wardrobe)` in `agent.py` is a single pass loop, not a multi turn LLM thing. it decides what to call by checking the session, and theres one real decision point: the empty search branch.

1. parse the query into description/size/max_price w regex (price after "under $"/"$", size after "size", everything else is the description after stripping filler, articles, and any "i wear ..." wardrobe context).
2. call `search_listings`.
3. **branch:** if the result is empty, set `session["error"]` to a specific message naming the constraints and return right there. it does NOT select an item or call suggest_outfit/create_fit_card.
4. otherwise `selected_item = results[0]`.
5. call `suggest_outfit(selected_item, wardrobe)`.
6. call `create_fit_card(outfit, selected_item)`.
7. return the session.

whats adaptive: a good query runs all 3 tools, an impossible one runs only search then stops w a helpful message. it never fires all 3 unconditionally.

## state management

the session dict from `_new_session` is the single source of truth for one run. nothing gets re entered or hardcoded between steps. each step writes its output into the session and the next step reads it back:
- parse writes `parsed`, search reads it and writes `search_results`.
- the branch reads `search_results`; on empty it writes `error` and returns.
- step 4 writes `selected_item = search_results[0]`. this exact dict is what both downstream tools get.
- suggest_outfit writes `outfit_suggestion`, create_fit_card reads that + `selected_item` and writes `fit_card`.
- `handle_query` in `app.py` reads `error` first (set = panel 1 only), else maps `selected_item`/`outfit_suggestion`/`fit_card` to the 3 panels.

u can prove the state is real: `selected_item` is the same object as `search_results[0]` and its the same object passed into both suggest_outfit and create_fit_card (theres a test asserting `session["selected_item"] is session["search_results"][0]`).

## error handling

| tool | failure mode | what the agent does | example from testing |
|------|--------------|---------------------|----------------------|
| search_listings | no match, returns `[]` | stops before any LLM call, shows a specific message + what to change | `"designer ballgown size XXS under $5"` -> "No listings matched \"designer ballgown\" in size XXS under $5. Try removing the size filter, raising your price ceiling, or describing the item more broadly." |
| suggest_outfit | empty wardrobe | falls back to general styling advice instead of crashing or returning "" | empty wardrobe + a graphic tee -> "This graphic tee has a grunge, streetwear vibe... pair it with high-waisted jeans and sneakers..." |
| create_fit_card | empty/whitespace outfit | returns a descriptive error string, never raises | `create_fit_card("", item)` -> "Couldn't create a fit card: no outfit description was provided. Run suggest_outfit first..." |

all 3 are covered by tests in `tests/` and were triggered by hand w the exact commands from the project instructions.

## spec reflection

**one way the spec helped:** writing the exact 7 step loop + the empty search branch + the scoring rule in planning.md before coding meant the implementation was basically transcription, no guessing. the documented top match (lst_006 for "vintage graphic tee" under $30) became an actual test assertion.

**one way it diverged:** the planning.md walkthrough assumed "vintage graphic tee" parses clean, but the raw query left the article "a" in the description, and that stray token tied lst_002 w lst_006 and flipped the top result. so i added article + "i wear ..." clause stripping in the parser, which wasnt in the original spec. couple smaller divergences too: platform values are lowercase in the data so i added title casing for captions, and the .env was utf-16 so i added an encoding fallback.

## ai usage

**1, the tools (search):** i gave claude my Tool 1 spec block (params + types, the "returns list[dict] best match first, [] on no match, never raises" contract, and the scoring rule) and had it implement `search_listings` using `load_listings()`. i had the output verified against the real data, which caught that the documented walkthrough ranking needed the article stripped and that `new_item` uses `title` not `name`. i revised: added the parser cleaning and kept search tokenization simple.

**2, the LLM tools:** i gave claude the Tool 2/3 spec blocks to implement `suggest_outfit` and `create_fit_card` on groq `llama-3.3-70b-versatile`. i overrode the price formatting so captions read "$18" not "$18.0", added platform title casing, and set the caption temperature to 1.0 after confirming low temp repeated itself across runs.

**3, the loop + wiring:** i gave claude the Planning Loop + State Management sections + the architecture diagram to write `run_agent` and `handle_query`. before trusting it i checked by inspection that the empty search branch returns early without calling the LLM tools and that `selected_item` is the same object as `search_results[0]`. i also caught and fixed a utf-16 `.env` crash w an encoding fallback.

## layout

```
fitfindr/
├── agent.py            # run_agent planning loop + query parsing
├── app.py              # gradio ui + handle_query
├── tools.py            # search_listings, suggest_outfit, create_fit_card
├── data/
│   ├── listings.json         # 40 mock listings
│   └── wardrobe_schema.json  # wardrobe format + example/empty wardrobes
├── utils/data_loader.py      # load_listings / get_example_wardrobe / get_empty_wardrobe
├── tests/
│   ├── test_tools.py   # per-tool tests incl every failure mode
│   └── test_agent.py   # agent-level failure + state-flow tests
└── planning.md         # the spec, written before the code
```
