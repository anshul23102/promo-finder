# The results page

One static page, five tabs, one header and one set of fonts. Dark, orange and Figtree, in the spirit of Kuku's own apps. Vanilla HTML, CSS and JS, no build step.

- **Promos.** A hero with a looping reel of the top three (hook, the cut, the cliffhanger), a run strip, then ranked cards lit at the top (the hook) and dimmed under a diagonal (the cliffhanger), each with why it works and the clip's script. CSV and JSON downloads. Rules-only cuts for episodes the AI did not judge are listed separately and labelled.
- **Season.** One row per episode with the promos drawn where they sit in it.
- **Quality.** A funnel (cuts found, cuts kept, why the rest were dropped), four checks and the known weak spots.
- **Run it.** Bring a show: files, a folder, one ZIP, pasted text or an example. The Python finder runs in a worker in this tab (`run/`); nothing is uploaded.
- **Review (optional).** `review.js` and `review.css` load the first time the tab opens. Plays a promo, lets you nudge its cut to a clean line break (checked against the 20 to 60 second rule) and mark keep / trim / pass, and downloads a handoff list. Marks stay in the browser.

## Run

    python3 ui-claude/serve.py --run <run folder> --pack <scripts.zip>

`data.js` contains script text. It is written under `private/` for real shows and must never be published. `index.html`, `app.css`, `app.js`, `review.*` and `fonts/` hold no show content (Figtree and Bricolage Grotesque, SIL Open Font License, see `fonts/NOTICE.txt`).
`build_data.py` writes `data.js`; `build_runner.py` adds the pinned Pyodide runtime and the worker (`run/`); `serve.py` does both if an unpacked `pyodide@0.29.5` sits at `private/pyodide-package`.
