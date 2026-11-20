# The results page

A small static web app that shows a finished run: the ranked promos, the quality checks and how to run the tool on another show.
Dark, orange and Figtree, in the spirit of Kuku's own apps. Vanilla HTML, CSS and JS, no build step.

- **Promos.** Each promo is a card lit at the top (the hook) and dimmed below a diagonal cut (the cliffhanger), with its segments,
  why it works and the clip's script (the first 3 seconds highlighted). CSV and JSON downloads. Rules-only cuts for episodes the AI
  did not judge are listed separately and labelled.
- **Quality.** Hard rules, the writers' own cliffhangers, episode coverage, what was thrown away and why, known weak spots, and a row per episode.
- **Run it.** The three ways to run the tool, and the input format. `run/` is the in-browser runner: drop in a script, get the promos.
- **Review (optional), `review/`.** Not part of the task. Plays a promo as the script unfolds, lets you nudge its cut to a clean line break (checked against the 20 to 60 second rule) and mark keep / trim / pass, then downloads a handoff list for an editor. Marks stay in the browser.

## Run

    python3 ui-claude/serve.py --run <run folder> --pack <scripts.zip>

`data.js` contains script text. It is written under `private/` for real shows and must never be published.
`index.html`, `app.css`, `app.js` and `fonts/` hold no show content (Figtree and Bricolage Grotesque, SIL Open Font License, see `fonts/NOTICE.txt`).
`build_data.py` writes `data.js`; `build_runner.py` adds the in-browser runner (`run/`) to a built site.
