# Promo Finder

Reads timestamped microdrama screenplays and finds the best 20-60 second promos: clips that **open on a hook**, **end on a cliffhanger** and **make sense to someone who has never seen the show**. It outputs the episode and in/out time of every segment, the hook, the cliffhanger, one line on why it works, a ranked posting plan, and an honest quality report.

Built for the Kuku AI Generalist assignment, Problem 1.

## How it works

```
screenplays -> 1 parse (code) -> 2 show guide (AI, 1 call) -> 3 editor picks moments by cue ID (AI, per episode)
            -> 4 cut builder enforces the rules (code) -> 5 cold viewer sees only the clip (AI)
            -> 6 ranking: shuffled groups + Bradley-Terry (AI) -> 7 posting plan (code) -> 8 quality report (code)
```

- **AI judges, code measures.** Models only ever name cue IDs. Code turns them into cuts on shot boundaries, keeps the hook inside the first 3 seconds, never splits a spoken line, and enforces 20-60 s.
- **The cold viewer** gets nothing but the clip, then says what it understood and what it is left wondering. Clips a stranger can't follow, or whose ending answers its own question, are dropped. Its account is shown to the editor.
- **Ranking** compares clips in shuffled groups over several rounds instead of trusting 1-10 scores, and reports the judge's position bias.
- **Posting order** favours early episodes (a new viewer lands on episode 1), holds back big spoilers and varies hook types.
- **A human decides.** The review page has keep / trim / pass and exports decisions. The post-first list also exports as an EDL for Premiere or Resolve.

## Run it

Python 3.11+. The pipeline itself has no dependencies.

```bash
cp .env.example .env          # add a free GEMINI_API_KEY from https://aistudio.google.com/apikey
python3 -m promo path/to/scripts.zip --model gemini --judge gemini:gemini-flash-lite-latest
python3 -m promo path/to/scripts.zip --model rules            # no AI: the baseline
python3 -m promo examples/last-edition --model ollama:qwen3:4b  # fully offline (slower, weaker)
```

Swap models with one flag: `--model groq`, `--model openrouter:<model>`, `--model openai:<model>`, or any OpenAI-compatible endpoint with `--model openai-compatible:<model>` plus `PROMO_BASE_URL` and `PROMO_API_KEY`. Every model answer is cached, so a re-run after a crash or rate limit resumes for free.

Web app (upload a ZIP, review in the browser):

```bash
pip install streamlit && streamlit run app.py
```

Outputs land in `private/runs/<time>/`: `index.html` (review page), `posting_plan.md`, `promos.csv`, `promos.json`, `evaluation.md`, `cutlist.edl`, `show_guide.json`, `rejected.json`, `ranking.json`, `model_calls.jsonl` (every raw model reply).

Tests: `python3 -m unittest discover -s tests`

## Limits

- It reads screenplays, not footage. It can't see whether a look lands, how fast a line is delivered, or whether a viewer really stops scrolling.
- The cold viewer and the ranking judge are models standing in for people. The quality report says how often they agree with the writers' own cliffhangers and with blind reference cuts, not how promos perform.
- Screenplay timestamps may drift from the final edit.

The supplied show is Kuku's confidential content and is not in this repository. `examples/` holds two original, made-up episodes for demos.
