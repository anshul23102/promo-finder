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
- **A person decides.** The tool only finds and orders the promos; an editor picks which to post. Each promo carries its episode, every segment's start and end, the hook, the cliffhanger and a one-line reason, as CSV, JSON and a 30 fps EDL reference (match frame rate and reel IDs against the real media before conforming).

An earlier version asked one model to pick whole promos (`--finder editor`). It could not keep picks inside 60 seconds and never beat a no-AI baseline; scoring beats and letting code search fixed both.

## Try it in your browser (no install, no upload)

The published page has a **Run it** tab (`#/run`). Choose one episode (`.txt`) or a ZIP of `.txt` episodes and it runs the same rules finder in your browser tab (the Python engine, compiled to WebAssembly with [Pyodide](https://pyodide.org) 0.29.5, Python 3.13) and opens the same review page on your result. There are no keys, no model calls and no analytics on that path, the script is read in memory, deleted when the run ends, and never written to browser storage. Results are labelled **rules candidates**: timing-checked material for an editor, not AI-judged promos.

- Limits: one `.txt` or one `.zip`, at most 25 MB, 200 episodes, 5 MB per episode, 60 MB unpacked. SRT and VTT subtitles are not read yet.
- AI runs, bigger shows and anything confidential stay on your computer (below). If the runtime cannot start, the page says why and the demo keeps working.
- Reviewers who cannot play the preview get a plain-text list of the same cuts under the result bar, and **Download all run files (.zip)** returns every output plus `contract.json`.
- Checked: the browser engine and native Python produce the same output file for file (`node tools/check_browser_parity.mjs`, part of `tools/release_check.sh`), on bundled inputs, a 50-episode synthetic show and the rejection cases.
- Runtime assets are pinned (`ui-claude/runtime.lock.json`, MPL-2.0 licence notice shipped beside them) and every file the page loads carries a content hash in its name, so a cached page cannot mix versions. Python versions tested: 3.13 (browser) and 3.15 (native).

## Run it

Python 3.11+. The pipeline itself has no dependencies.

**Start here (safe, no key, no AI, nothing leaves your machine):**

```bash
python3 -m promo examples/the-last-edition --model rules      # the made-up demo show: finds a timing-checked cut per episode
python3 ui-claude/workbench.py                                # or drop episode files into a local page and get the results pages
```

**Real or confidential scripts** (for example a Kuku pack): use a backend approved for that data: a local model, an endpoint Kuku supplies, or Groq with Zero Data Retention switched on in its console.

```bash
python3 -m promo path/to/scripts.zip --model rules            # no AI: the reproducible baseline
python3 -m promo path/to/scripts.zip --model ollama:qwen3:4b --no-guide   # fully offline: works for beat scoring, slow on a laptop
python3 -m promo path/to/scripts.zip --model openai-compatible:<model> --judge openai-compatible:<other-model>   # with PROMO_BASE_URL and PROMO_API_KEY
python3 -m promo path/to/scripts.zip --model groq:openai/gpt-oss-120b --judge groq:qwen/qwen3.8-27b --no-guide \
    --episodes 1-12                                              # Groq free plan (switch on Zero Data Retention first)
```

**Hosted free models on made-up or public scripts only.** Google's unpaid Gemini tier says not to submit confidential information ([terms](https://ai.google.dev/gemini-api/terms)), so use it only on `examples/`:

```bash
cp .env.example .env          # add a free GEMINI_API_KEY from https://aistudio.google.com/apikey
python3 -m promo examples/the-last-edition --model gemini --judge "gemini:gemma-4-26b-a4b-it|gemini-3.1-flash-lite"
```

With no `--model` the run uses the rules only (no AI, nothing leaves your computer). With a model, each shortlisted promo also gets one extra call that writes a single sentence on why it works from the clip itself (`--no-why` skips it and quotes the clip instead). The **hook** shown everywhere is what is on screen in the first 3 seconds, not a model's paraphrase.

Swap models with one flag (`a|b` is a fallback chain; an overloaded model is skipped for 5 minutes): `--model groq`, `--model openrouter:<model>`, `--model openai:<model>`, or any OpenAI-compatible endpoint with `--model openai-compatible:<model>` plus `PROMO_BASE_URL` and `PROMO_API_KEY`. Recovery tries alternate cuts for episodes with no passing pick. Each run includes a per-episode coverage ledger and a review candidate where a valid alternate exists. Use `--no-recover` to skip the extra model calls or `--rounds 0` to rank by the viewer rubric without the tournament. On Groq's free plan each model gets 8K tokens a minute and 200K a day; one episode costs about 7.5K tokens to score, so run about 25 episodes a day (`--episodes`) and repeat: cached episodes cost nothing. The client paces itself, and stops with a clear message instead of sleeping when a daily cap is hit. Every model answer is cached, so a re-run after a crash or rate limit resumes for free.

On macOS, the private project’s Finder launcher opens a timing-only review without a model. Launch it from Terminal with PROMO_LOCAL_MODEL=qwen3:4b to request local AI.

Browser version (no install): the **Run it** tab of the live page takes a ZIP, a folder, several episode files or pasted text and runs the finder in your browser tab. On your own computer, `python3 ui-claude/workbench.py` does the same with an AI engine of your choice.

Outputs land in `private/runs/<time>/`: `index.html` (review page), `posting_plan.md`, `promos.csv`, `promos.json`, `evaluation.md`, `coverage.json`, `cutlist.edl`, `show_guide.json`, `rejected.json`, `ranking.json`, `model_calls.jsonl` (every raw model reply).

Tests: `python3 -m unittest discover -s tests`

Before a release: `tools/release_check.sh` runs the tests, a model-swap smoke test against a local stand-in for an OpenAI-compatible endpoint (structured answers, provenance, cache replay under a new folder, wrong key, HTTP 500), a fresh build of the demo and the browser runner, and Pyodide-versus-Python parity. It needs `node` and `npm`.

**Integration contract.** `promo/contract.py` writes `contract.json` (`promo-finder.run/1`): input identity, ordered segments in integer centiseconds with their opening and closing evidence, run state, hashes and an idempotency key, and a separate editor handoff document. See [contract/README.md](contract/README.md) and the golden examples in `contract/examples/`.

## The results page

One page with five tabs, the same header and fonts throughout. **Promos** is the answer: a reel that plays the top three (hook, cut, cliffhanger), then every promo in posting order with its segments, hook, cliffhanger, why it works and the clip's script, with CSV and JSON downloads. **Season** shows every episode as a row with the promos drawn where they sit in it. **Quality** shows how many cuts were found and kept, four checks (each with what it cannot prove) and the known weak spots. **Run it** takes any show: drop or pick episode files, a whole folder or one ZIP, paste a script, or try an example, and the finder runs inside the tab (no AI, no upload) and shows the same pages. **Review (optional)** is not part of the task: it plays each promo as the script unfolds, lets you nudge its cut to a clean line break and records keep, trim or pass for an editor handoff. Code lives in `ui-claude/`.

- **Try it now, no setup:** [live demo](https://anshul23102.github.io/promo-finder/) with a made-up show (`examples/the-last-edition/`, seven episodes). The demo data is synthetic; it contains no Kuku content.
- **Use it on your own scripts, in the browser:** `python3 ui-claude/workbench.py` opens a page where you drop episode files (or one ZIP), pick an engine (no AI, Groq, Gemini or a local model) and get the results pages. It binds to 127.0.0.1 only, checks a per-launch token, and asks you to confirm before any script text is sent to an AI provider.
- **View a finished run (stays on your machine):**

```bash
python3 ui-claude/serve.py --run private/runs/<your-run> --pack path/to/scripts.zip
```

It builds `private/ui-claude/` and serves 127.0.0.1 only. The built `data.js` contains script text, so keep it out of anything you publish. Fonts: Figtree and Bricolage Grotesque, SIL OFL (`ui-claude/fonts/NOTICE.txt`).

## Limits

- It reads screenplays, not footage. It can't see whether a look lands, how fast a line is delivered, or whether a viewer really stops scrolling.
- The cold viewer and the ranking judge are models standing in for people. The quality report checks the cuts against hard rules, the writers' own cliffhangers and a person's blind ratings, not how promos perform.
- Screenplay timestamps may drift from the final edit.

The supplied show is Kuku's confidential content and is not in this repository. `examples/` holds original, made-up episodes for demos.
