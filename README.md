# Promo Finder

Reads timestamped microdrama screenplays and finds the best 20-60 second promos: clips that **open on a hook**, **end on a cliffhanger** and **make sense to someone who has never seen the show**. It outputs the episode and in/out time of every segment, the hook, the cliffhanger, one line on why it works, a ranked posting plan, and an honest quality report.

Built for the Kuku AI Generalist assignment, Problem 1.

## How it works

The brief defines a promo by three properties that live in different places: the **hook** lives in the first 3 seconds, the **cliffhanger** lives in the last beat, and **"makes sense on its own"** belongs to the whole clip. So each is judged where it lives:

```
screenplays -> parse (code) -> show guide (AI, 1 call) -> beat scores (AI, 1 call per episode)
            -> search every legal opening x ending pair (code) -> cold viewer sees only the clip (AI)
            -> ranking: shuffled groups + Bradley-Terry (AI) -> posting plan (code) -> quality report (code)
```

- **Beat scores.** For every cue the model answers two small questions, 0-3: would a clip *starting* here stop a stranger, and would a clip *ending* here leave a sharp question open? It never writes a timestamp or does clock arithmetic.
- **Code does the search and the rules.** Every legal opening x ending pair: 20-60 s, cut on camera shots, hook inside the first 3 seconds, never inside a spoken line, never opening on a dangling line.
- **The cold viewer** gets only the clip and its original speaker labels, then says what it understood and what it is left wondering. Clips a stranger can't follow, or whose ending answers its own question, are dropped. Its account is shown to the editor.
- **Ranking** compares clips in shuffled groups over several rounds instead of trusting 1-10 scores, and reports the judge's position bias.
- **Posting order** favours early episodes (a new viewer lands on episode 1), holds back big spoilers, posts one promo per episode first.
- **A human decides.** The review page has keep / trim / pass and exports decisions; `--decisions <csv>` scores the tool against them. The post-first list also exports a 30 fps EDL reference. Match frame rate and reel IDs against the actual media before conforming.

An earlier version asked one model to pick whole promos (`--finder editor`). It could not keep picks inside 60 seconds and never beat a no-AI baseline; scoring beats and letting code search fixed both.

## Run it

Python 3.11+. The pipeline itself has no dependencies.

```bash
cp .env.example .env          # add a free GEMINI_API_KEY from https://aistudio.google.com/apikey
python3 -m promo path/to/scripts.zip --model gemini --judge "gemini:gemma-4-26b-a4b-it|gemini-3.1-flash-lite"
python3 -m promo path/to/scripts.zip --model groq:openai/gpt-oss-120b --judge groq:qwen/qwen3.8-27b --no-guide \
    --episodes 1-12                                              # Groq free plan (switch on Zero Data Retention first)
python3 -m promo path/to/scripts.zip --model rules            # no AI: the baseline
python3 -m promo examples/last-edition --model ollama:qwen3:4b  # fully offline: works for beat scoring, slow on a laptop
```

Use the original examples when testing the unpaid Gemini API. Its terms say not to submit confidential information. For a Kuku pack run, use local Ollama or an endpoint approved for that data. [Gemini API terms](https://ai.google.dev/gemini-api/terms)

Swap models with one flag (`a|b` is a fallback chain; an overloaded model is skipped for 5 minutes): `--model groq`, `--model openrouter:<model>`, `--model openai:<model>`, or any OpenAI-compatible endpoint with `--model openai-compatible:<model>` plus `PROMO_BASE_URL` and `PROMO_API_KEY`. Recovery tries alternate cuts for episodes with no passing pick. Each run includes a per-episode coverage ledger and a review candidate where a valid alternate exists. Use `--no-recover` to skip the extra model calls or `--rounds 0` to rank by the viewer rubric without the tournament. On Groq's free plan each model gets 8K tokens a minute and 200K a day; one episode costs about 7.5K tokens to score, so run about 25 episodes a day (`--episodes`) and repeat: cached episodes cost nothing. The client paces itself, and stops with a clear message instead of sleeping when a daily cap is hit. Every model answer is cached, so a re-run after a crash or rate limit resumes for free.

On macOS, the private project’s Finder launcher opens a timing-only review without a model. Launch it from Terminal with PROMO_LOCAL_MODEL=qwen3:4b to request local AI.

Web app (upload a ZIP, review in the browser):

```bash
pip install -r requirements.txt
streamlit run app.py
```

Outputs land in `private/runs/<time>/`: `index.html` (review page), `posting_plan.md`, `promos.csv`, `promos.json`, `evaluation.md`, `coverage.json`, `cutlist.edl`, `show_guide.json`, `rejected.json`, `ranking.json`, `model_calls.jsonl` (every raw model reply).

Tests: `python3 -m unittest discover -s tests`

## Limits

- It reads screenplays, not footage. It can't see whether a look lands, how fast a line is delivered, or whether a viewer really stops scrolling.
- The cold viewer and the ranking judge are models standing in for people. The quality report says how often they agree with the writers' own cliffhangers and with blind reference cuts, not how promos perform.
- Screenplay timestamps may drift from the final edit.

The supplied show is Kuku's confidential content and is not in this repository. `examples/` holds two original, made-up episodes for demos.
