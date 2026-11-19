# The cutting room

A local web app for reviewing the promos the tool found. Dark, orange and Figtree in the spirit of Kuku's own apps,
built around what the job really is: watching a vertical cut and deciding.

- **The reel** plays a take as the script unfolds: shot HUD, narration, kinetic subtitles with speaker chips, a backdrop
  that shifts with the speaker. There is no footage, only script, and the app says so by never pretending otherwise.
- **The 3-second gate** is a ring around the reel that fills for the first three seconds, then reads "Gate cleared" or "Quiet start".
- **The cut to black** at the end shows the question the clip leaves hanging, with a peek at what happens next.
- **The vertical timeline** beside the reel lets you trim. Handles land only on clean line breaks and the slate re-checks the
  20 to 60 second rule, the 3-second rule, dangling openings and mid-sentence endings as you drag.
- **The season strip** is a film strip of every episode with a pulse line of where the tool saw hooks (orange) and cliffhangers (gold).
- **The slate** holds the take's metadata and the keep / trim / pass verdict.
- **Blind mode** hides every AI opinion, shuffles the takes and flattens the strip, so your rating is your own.

Export writes a CSV the tool can score: `python3 -m promo ... --review "cutting-room.csv|human|You"`.

## Run

    python3 ui-claude/serve.py --run private/runs/v5-eval-final --pack <scripts.zip> --beats private/runs/v4-full \
        --review "me|You|human|ratings.csv"

Keys: Space play, left/right take, K/T/P verdict, [ ] set in or out, R restart, B blind, F theatre, ? help.

## Privacy

`index.html`, `app.css`, `app.js`, `fonts/` hold no show content. The built `data.js` contains script text and ratings:
it is written under `private/` and must never be published. Fonts are Figtree and Bricolage Grotesque (SIL Open Font License, see `fonts/NOTICE.txt`).

## Demo site

The published demo is built from a made-up show:

    python3 ui-claude/build_data.py --run <demo run> --pack examples/the-last-edition --beats <demo run> --out site --demo
