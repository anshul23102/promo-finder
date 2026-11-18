"""Render a self-contained local review screen for ranked screenplay excerpts."""

import hashlib
import json
from html import escape


def _text(value):
    return escape(str(value) if value is not None else "", quote=True)


def _number(value):
    return f"{value:g}" if isinstance(value, (int, float)) else str(value or "0")


def _queue_entry(index, promo):
    rank = _text(promo.get("rank", index + 1))
    episode = _text(promo.get("episode"))
    hook = _text(promo.get("hook") or "Untitled cut")
    duration = _text(_number(promo.get("duration_s")))
    return f"""
    <li><a class="queue-link" href="#cut-{index}" data-index="{index}">
      <span class="rank">{rank}</span>
      <span class="queue-copy"><span class="queue-meta">Episode {episode} · {duration}s</span>
      <span class="queue-hook">{hook}</span><span class="queue-decision" hidden></span></span>
    </a></li>"""


def _cut(index, promo):
    rank = _text(promo.get("rank", index + 1))
    episode = _text(promo.get("episode"))
    hook = _text(promo.get("hook") or "Untitled cut")
    duration = _text(_number(promo.get("duration_s")))
    segments = promo.get("segments") or [promo]
    segment_rows = []
    segment_cells = []
    for segment in segments:
        ep = segment.get("episode", promo.get("episode"))
        start = segment.get("start", promo.get("start"))
        end = segment.get("end", promo.get("end"))
        segment_cells.append(f"Ep {ep} [{start} – {end}]")
        segment_rows.append(
            '<tr><td>Episode ' + _text(ep) + '</td><td>' + _text(start)
            + '</td><td>' + _text(end) + '</td></tr>'
        )
    method = _text(promo.get("method") or "Unspecified")
    why = _text(promo.get("why") or "No rationale recorded.")
    next_beat = _text(promo.get("next_beat") or "No following beat supplied.")
    opening = _text(promo.get("opening_evidence") or "No opening evidence supplied.")
    closing = _text(promo.get("closing_evidence") or "No closing evidence supplied.")
    cliffhanger = _text(promo.get("cliffhanger") or "No cliffhanger supplied.")
    opening_block = ""
    if opening != hook:
        opening_block = f"<section><h3>Opening evidence</h3><blockquote>{opening}</blockquote></section>"
    hook_label = "Opening hook" if opening != hook else "Opening hook · exact evidence"
    view = promo.get("viewer") or {}
    stranger = ""
    if view:
        grades = " · ".join(f"{label}: {_text(view.get(key, ''))}" for label, key in
                            (("first 3 s", "first_3s"), ("follows it", "makes_sense"), ("ending", "ending")))
        stranger = (f'<section class="stranger"><h3>What a stranger understood (clip only)</h3>'
                    f'<p>{_text(view.get("who"))} {_text(view.get("situation"))}</p>'
                    f'<p><strong>Left wondering:</strong> {_text(view.get("open_question"))}</p>'
                    f'<p class="grades">{grades} · confused by: {_text(view.get("confusing"))}</p></section>')
    script = ""
    if promo.get("script"):
        script = f'<details class="spoiler"><summary>Clip script</summary><pre class="script">{_text(promo["script"])}</pre></details>'
    if promo.get("plan"):
        plan_label = {"post_first": "Post first", "library": "Library", "hold_back": "Hold back", "alternate": "Alternate"}.get(promo["plan"], promo["plan"])
        method = f'{method}<br>{_text(plan_label)}: {_text(promo.get("plan_reason", ""))}'
    next_time = promo.get("next_beat_time")
    next_label = "Reveal the next beat" + (f" at {_text(next_time)}" if next_time else "")
    actions = "".join(
        f'<button type="button" data-decision="{d}" aria-pressed="false">{d.title()}</button>'
        for d in ("keep", "trim", "pass")
    )
    return f"""
    <article class="cut" id="cut-{index}" data-index="{index}" data-rank="{rank}"
         data-segments="{_text(' | '.join(segment_cells))}" data-duration="{duration}"
         aria-labelledby="title-{index}">
      <div class="cut-meta"><span>Rank {rank}</span><span>Episode {episode}</span>
        <span class="length">{duration} seconds</span></div>
      <p class="hook-label">{hook_label}</p>
      <h2 class="cut-title" tabindex="-1" id="title-{index}">{hook}</h2>
      <table class="timings"><caption>Cut list</caption>
        <thead><tr><th scope="col">Source</th><th scope="col">In</th><th scope="col">Out</th></tr></thead>
        <tbody>{''.join(segment_rows)}</tbody></table>
      <section class="evidence" aria-label="Cut evidence">
        {opening_block}
        <section><h3>Closing evidence</h3><blockquote>{closing}</blockquote></section>
      </section>
      <div class="reason"><h3>Cliffhanger</h3><p>{cliffhanger}</p>
        <h3>Why cut here?</h3><p>{why}</p></div>
      {stranger}
      <details class="spoiler"><summary>{next_label}</summary><p>{next_beat}</p></details>
      {script}
      <div class="review-tools js-only"><div><h3>Review decision</h3>
        <div class="decisions" role="group" aria-label="Review decision for rank {rank}">{actions}</div></div>
        <p class="method">Selection method<br><strong>{method}</strong></p></div>
    </article>"""


def render_report(result: dict) -> str:
    """Return static HTML. Browser-only annotations never mutate the raw results."""
    promos = result.get("promos") or []
    show = result.get("show") or "Untitled show"
    summary = result.get("summary") or {}
    signature = json.dumps([show, promos], sort_keys=True, ensure_ascii=False)
    run_id = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:24]
    cut_count = len(promos)
    count_label = f"{cut_count} candidate{'s' if cut_count != 1 else ''}"
    episodes = int(summary.get("episodes") or 0)
    episode_label = f"{episodes} episode{'s' if episodes != 1 else ''}"
    cue_label = f"{int(summary.get('cues') or 0):,} timed cues"
    run_details = ""
    if summary.get("model"):
        run_details = (
            '<details class="run-details"><summary>Run details</summary><p>'
            f'Model: {_text(summary["model"])}<br>Episodes with a model decision: '
            f'{_text(summary.get("model_success", 0))}<br>Fallbacks: '
            f'{_text(summary.get("fallback", 0))}</p></details>'
        )
    if promos:
        queue = "".join(_queue_entry(i, p) for i, p in enumerate(promos))
        cuts = "".join(_cut(i, p) for i, p in enumerate(promos))
        body = f"""
        <div class="workspace"><nav class="queue" aria-label="Ranked cut queue">
          <div class="queue-head"><h2>Ranked cuts</h2><span id="progress">0 of {cut_count} reviewed</span></div>
          <ol>{queue}</ol></nav><div class="detail">{cuts}</div></div>"""
        export = '<button class="export js-only" type="button" id="export">Export review CSV</button>'
    else:
        body = """<section class="empty"><h2>No cuts to review</h2>
          <p>This run returned zero candidates. Check the input and the run summary before rerunning the finder.</p></section>"""
        export = ""
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
      <link rel="icon" href="data:,"><meta name="viewport" content="width=device-width,initial-scale=1">
      <title>{_text(show)} · Promo review</title><style>{_CSS}</style></head>
      <body data-run="{run_id}"><a class="skip" href="#main">Skip to review</a>
      <header class="banner"><div class="wrap banner-inner"><div class="brand">
      <span class="mark" aria-hidden="true"></span>Promo Finder</div>{export}</div></header>
      <main class="wrap" id="main"><div class="heading"><div><p class="overline">Screenplay review</p>
        <h1>{_text(show)}</h1><div class="stats"><span>{_text(episode_label)}</span>
        <span>{_text(cue_label)}</span><span>{count_label}</span></div></div>{run_details}</div>
        <noscript><p>All cuts are listed below. Enable JavaScript to save decisions and export your review.</p></noscript>
        <p id="notice" class="notice" role="status"></p>{body}</main>
      <script>{_JS}</script></body></html>"""


_CSS = """
:root {color-scheme:light;--ink:#1d2131;--muted:#525b6a;--rule:#d7dce2;--canvas:#f4f6f8;
 --accent:#364199;--active:#e9edff;--night:#272741;--focus:#9a4b00;
 font:16px/1.52 "Atkinson Hyperlegible Next","Helvetica Neue",Arial,sans-serif;}
* {box-sizing:border-box} body {margin:0;background:var(--canvas);color:var(--ink)}
.wrap {width:min(1160px,calc(100% - 64px));margin:0 auto}
h1,h2,h3,p,blockquote,ol {margin:0} button,a,summary {touch-action:manipulation}
button,summary {font:inherit;cursor:pointer} a {color:inherit}
:focus-visible {outline:3px solid var(--focus);outline-offset:3px}
.skip {position:absolute;top:-100px;left:12px;z-index:5;padding:8px 14px;background:white}
.skip:focus {top:8px}
.banner {background:var(--night);color:#fff}.banner-inner {min-height:60px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.brand {display:flex;align-items:center;gap:12px;font-weight:720;letter-spacing:-.025em;font-size:1.08rem}
.mark {width:26px;height:20px;display:inline-block;position:relative;border:2px solid #d6dcff;border-radius:2px}
.mark:after {content:"";position:absolute;left:45%;top:-2px;height:20px;width:4px;transform:skew(-20deg);background:#d6dcff;border:2px solid var(--night);border-block:0}
.export {border:1px solid #898ba5;background:transparent;color:white;border-radius:5px;padding:6px 12px;font-size:.86rem}
.export:hover {background:#393954}.export:focus-visible {outline-color:#ffc780}
.heading {padding:36px 0 27px;display:flex;justify-content:space-between;gap:24px;align-items:flex-end}
.overline,.queue-meta,.queue-head span,.cut-meta,.method,.stats,.run-details {color:var(--muted);font-size:.83rem}
.overline {margin-bottom:4px} h1 {font-size:clamp(1.65rem,3.7vw,2.85rem);font-weight:670;line-height:1.13;letter-spacing:-.047em;overflow-wrap:anywhere}
.stats,.cut-meta {display:flex;gap:8px 16px;flex-wrap:wrap;align-items:center;font-variant-numeric:tabular-nums}
.stats {margin-top:10px}.stats span+span {border-left:1px solid #b8bfcd;padding-left:16px}
.run-details {flex:none}.run-details p {padding:6px 0} summary {font-weight:600}
.workspace {display:grid;grid-template-columns:minmax(220px,30%) minmax(0,1fr);gap:24px;align-items:start;padding-bottom:48px}
.queue,.cut,.empty {background:white;border:1px solid var(--rule);border-radius:9px}
.queue {overflow:hidden}.queue-head {padding:17px 18px 13px}.queue-head h2,.empty h2 {font-size:1.15rem;letter-spacing:-.025em}
.queue ol {list-style:none;padding:0;max-height:72vh;overflow-y:auto;overscroll-behavior:contain}
.queue li {border-top:1px solid var(--rule)}
.queue-link {display:grid;grid-template-columns:25px minmax(0,1fr);gap:8px;padding:13px 15px;text-decoration:none;border-left:4px solid transparent}
.queue-link:hover {background:#f1f3f8}.queue-link[aria-current="true"] {border-left-color:var(--accent);background:var(--active)}
.queue-link:focus-visible {outline-offset:-3px}
.rank {font-variant-numeric:tabular-nums;color:var(--muted)}
.queue-copy {display:grid;gap:3px}.queue-hook {font-size:.94rem;line-height:1.35;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.queue-decision {width:fit-content;color:var(--accent);font-size:.77rem;font-weight:bold}
.cut {padding:clamp(18px,3vw,37px);margin-bottom:16px;scroll-margin-top:12px}
.cut-meta>span:first-child {font-weight:750;color:var(--accent)}.cut-meta .length {margin-left:auto}
.hook-label {color:var(--muted);font-size:.81rem;margin:12px 0 0}.cut-title {margin:3px 0 22px;font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
 font-size:clamp(1.5rem,2.7vw,2.25rem);letter-spacing:-.028em;line-height:1.17;font-weight:600;overflow-wrap:anywhere}
.timings {width:100%;border-collapse:collapse;margin:0 0 21px;background:#f4f5f9;font-variant-numeric:tabular-nums}
.timings caption {text-align:left;font-weight:650;font-size:1rem;margin-bottom:5px}
.timings th,.timings td {padding:5px 13px;text-align:left}.timings th {border-bottom:1px solid var(--rule);font-size:.82rem;color:var(--muted);font-weight:550}
.timings td {font-family:"SFMono-Regular",Consolas,monospace;font-size:.88rem;padding-bottom:7px}
.evidence {display:grid;gap:14px;border-left:3px solid #a8afe3;padding-left:16px;margin-bottom:20px}
h3 {font-size:.94rem;font-weight:680}.evidence blockquote,.reason p,.spoiler p {margin-top:4px;overflow-wrap:anywhere}
.evidence blockquote {color:#34394c;white-space:pre-line}.reason h3:not(:first-child) {margin-top:12px}
.spoiler {margin-top:16px}.spoiler summary {color:var(--accent);font-size:.91rem;display:list-item}
.spoiler p {padding:8px 12px;background:#f4f5f9}.review-tools {display:flex;align-items:center;justify-content:space-between;gap:16px;margin-top:22px;padding-top:16px;border-top:1px solid var(--rule)}
.decisions {display:flex;gap:6px;margin-top:7px}.decisions button {min-height:36px;border:1px solid #a6aebc;border-radius:4px;background:white;padding:4px 16px;color:var(--ink);font-size:.9rem;font-weight:600}
.decisions button:hover {background:#f0f2fa}.decisions button[aria-pressed="true"] {background:var(--accent);color:white;border-color:var(--accent)}
.method {text-align:right;overflow-wrap:anywhere}.method strong {color:var(--ink);font-weight:550}
.stranger {background:#f4f5f9;border-radius:6px;padding:12px 14px;margin-top:16px}.stranger p {margin-top:4px}
.grades {color:var(--muted);font-size:.84rem}.script {white-space:pre-wrap;font-size:.8rem;line-height:1.45;max-height:40vh;overflow:auto;background:#f4f5f9;padding:10px}
.empty {padding:26px}.empty p {margin-top:6px}
.notice {font-size:.85rem;color:var(--muted);margin-bottom:8px}.notice:empty {display:none}
[hidden],.js-only {display:none!important}.ready .js-only {display:flex!important}
@media (max-width:720px) {.wrap {width:calc(100% - 28px)}.workspace {grid-template-columns:minmax(0,1fr);gap:14px}
 .queue ol {max-height:160px}.heading {padding:22px 0 17px;align-items:start;flex-direction:column;gap:9px}
 .queue-head {padding:10px 14px;display:flex;align-items:baseline;justify-content:space-between;gap:8px}
 .queue-link {padding:9px 12px}.queue-meta {font-size:.78rem}.cut-title {margin-bottom:15px}
 .cut {scroll-margin-top:6px}.review-tools {align-items:flex-start;flex-wrap:wrap}.method {text-align:left}}
@media (max-width:380px) {.stats {gap:5px 8px}.stats span+span {padding-left:8px}.decisions button {padding-inline:13px}}
@media print {.banner,.queue,:root.ready .review-tools,.export,.spoiler,.run-details,.notice {display:none!important}
 .workspace {display:block}.cut[hidden] {display:block!important}.wrap {width:100%}.cut {break-inside:avoid}.heading {padding-top:0}}
"""


_JS = r"""
(() => {
  const articles = [...document.querySelectorAll(".cut")];
  if (!articles.length) return;
  const links = [...document.querySelectorAll(".queue-link")];
  const key = "promo-finder.review.v1." + document.body.dataset.run;
  const allowed = ["keep", "trim", "pass"];
  let choices = {};
  let canSave = true;
  try {
    const stored = JSON.parse(localStorage.getItem(key) || "{}");
    if (stored && typeof stored === "object" && !Array.isArray(stored)) choices = stored;
  } catch (_) { canSave = false; }

  function applyDecisions() {
    let count = 0;
    articles.forEach((article, index) => {
      const choice = choices[String(index)];
      const reviewed = allowed.includes(choice);
      const label = links[index].querySelector(".queue-decision");
      label.hidden = !reviewed;
      label.textContent = reviewed ? choice[0].toUpperCase() + choice.slice(1) : "";
      if (reviewed) count++;
      article.querySelectorAll("[data-decision]").forEach(button => {
        button.setAttribute("aria-pressed", String(button.dataset.decision === choice));
      });
    });
    document.getElementById("progress").textContent = count + " of " + articles.length + " reviewed";
  }

  function select(index) {
    if (canSave) document.getElementById("notice").textContent = "";
    articles.forEach((article, i) => {
      article.hidden = i !== index;
      if (i === index) links[i].setAttribute("aria-current", "true");
      else links[i].removeAttribute("aria-current");
    });
  }

  function selectFromHash() {
    const index = articles.findIndex(a => "#" + a.id === location.hash);
    select(index < 0 ? 0 : index);
  }

  links.forEach((link, index) => {
    link.addEventListener("click", event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      select(index);
      if (location.hash !== link.hash) location.hash = link.hash;
      articles[index].querySelector("h2").focus({preventScroll:true});
      if (matchMedia("(max-width:720px)").matches) articles[index].scrollIntoView();
    });
    link.addEventListener("keydown", event => {
      let target;
      if (event.key === "ArrowDown") target = Math.min(index + 1, links.length - 1);
      else if (event.key === "ArrowUp") target = Math.max(index - 1, 0);
      else if (event.key === "Home") target = 0;
      else if (event.key === "End") target = links.length - 1;
      else return;
      event.preventDefault();
      links[target].focus();
    });
  });
  addEventListener("hashchange", selectFromHash);
  document.addEventListener("click", event => {
    const button = event.target.closest("[data-decision]");
    if (!button) return;
    const index = button.closest(".cut").dataset.index;
    const choice = button.dataset.decision;
    if (choices[index] === choice) delete choices[index];
    else choices[index] = choice;
    try { localStorage.setItem(key, JSON.stringify(choices)); }
    catch (_) { canSave = false; }
    applyDecisions();
    const status = choices[index] ? choices[index] : "unreviewed";
    const warning = canSave ? "" : " Browser storage unavailable. Export a CSV to keep decisions.";
    document.getElementById("notice").textContent = "Rank " + articles[Number(index)].dataset.rank + " marked " + status + "." + warning;
  });

  function csvCell(value) {
    let text = String(value);
    if (/^\s*[=+@-]/.test(text)) text = "'" + text;
    return '"' + text.replace(/"/g, '""') + '"';
  }

  document.getElementById("export").addEventListener("click", () => {
    const rows = [["rank","decision","segments_in_order","duration_seconds","hook","cliffhanger","why","next_beat"]];
    articles.forEach((article, index) => {
      const d = article.dataset;
      const choice = allowed.includes(choices[index]) ? choices[index] : "unreviewed";
      const reasons = article.querySelectorAll(".reason p");
      rows.push([d.rank, choice, d.segments, d.duration, article.querySelector(".cut-title").textContent,
        reasons[0].textContent, reasons[1].textContent, article.querySelector(".spoiler p").textContent]);
    });
    const csv = rows.map(row => row.map(csvCell).join(",")).join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], {type:"text/csv;charset=utf-8"}));
    const a = document.createElement("a");
    a.href = url; a.download = "promo-review-" + document.body.dataset.run.slice(0,8) + ".csv";
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
  });
  selectFromHash();
  applyDecisions();
  document.documentElement.classList.add("ready");
})();
"""
