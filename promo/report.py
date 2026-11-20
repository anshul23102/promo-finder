"""Render a self-contained local review screen for ranked screenplay excerpts."""

import hashlib
import json
from html import escape


def _text(value):
    return escape(str(value) if value is not None else "", quote=True)


def _number(value):
    return f"{value:g}" if isinstance(value, (int, float)) else str(value or "0")


_PLAN_LABELS = {
    "post_first": "Post first",
    "library": "Library",
    "hold_back": "Hold back",
    "alternate": "Alternate",
}


def _queue_entry(index, promo):
    rank = _text(promo.get("rank", index + 1))
    episode = _text(promo.get("episode"))
    hook = _text(promo.get("hook") or "Untitled cut")
    duration = _text(_number(promo.get("duration_s")))
    return f"""
    <li><a class="queue-link" href="#cut-{index}" data-index="{index}">
      <span class="rank" aria-label="Rank {rank}">{rank}</span>
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
    opening = str(promo.get("opening_evidence") or "No opening evidence supplied.")
    frame_class = "frame-opening compact" if len(opening) > 115 else "frame-opening"
    closing = _text(promo.get("closing_evidence") or "No closing evidence supplied.")
    cliffhanger = _text(promo.get("cliffhanger") or "No cliffhanger supplied.")
    plan = promo.get("plan")
    plan_label = _text(_PLAN_LABELS.get(plan, plan))
    plan_badge = f'<span class="placement">{plan_label}</span>' if plan else ""
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
    if plan and promo.get("plan_reason"):
        method = f'{method}<br>{plan_label}: {_text(promo["plan_reason"])}'
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
      <div class="screening">
        <div class="stage">
          <div class="frame">
            <div class="frame-meta"><span>EP {episode}</span><span>9:16</span></div>
            <div class="{frame_class}" tabindex="0" role="region" aria-label="First 3 seconds"><p>First 3 seconds</p><blockquote>{_text(opening)}</blockquote></div>
            <div class="frame-meta"><span>Script preview</span><span>{duration}s</span></div>
          </div>
        </div>
        <div class="editor">
          <div class="cut-meta"><span>Rank {rank}</span><span>Episode {episode}</span>{plan_badge}</div>
          <p class="hook-label">Opening hook</p>
          <h2 class="cut-title" tabindex="-1" id="title-{index}">{hook}</h2>
          <div class="reason"><h3>Cliffhanger</h3><p>{cliffhanger}</p>
            <h3>Why cut here?</h3><p>{why}</p></div>
          <div class="review-tools js-only"><h3>Review decision</h3>
            <div class="decisions" role="group" aria-label="Review decision for rank {rank}">{actions}</div>
            <p class="decision-status" role="status"></p>
          </div>
        </div>
      </div>
      <div class="cut-notes">
      <table class="timings"><caption>Source timecodes <span>{duration}s total</span></caption>
        <thead><tr><th scope="col">Source</th><th scope="col">In</th><th scope="col">Out</th></tr></thead>
        <tbody>{''.join(segment_rows)}</tbody></table>
      <section class="evidence" aria-label="Cut evidence">
        <section><h3>Closing evidence</h3><blockquote>{closing}</blockquote></section>
      </section>
      {stranger}
      <details class="spoiler"><summary>{next_label}</summary><p>{next_beat}</p></details>
      {script}
      <p class="method">Selection method<br><strong>{method}</strong></p>
      </div>
    </article>"""


def _coverage(items):
    if not items:
        return ""
    rows = []
    for item in items:
        cut = item.get("cut")
        segments = " / ".join(f"{part['start']}–{part['end']}" for part in (cut or {}).get("segments", []))
        evidence = ""
        if cut:
            fields = (("Opening", "opening"), ("Ending", "ending"), ("Following beat", "next_beat"))
            evidence = "<details><summary>Script evidence</summary>" + "".join(
                f"<p><strong>{label}</strong> {_text(cut[key])}</p>"
                for label, key in fields if cut.get(key)
            ) + "</details>"
        rows.append(f"<tr><th scope='row'>{_text(item['episode'])}</th>"
                    f"<td>{_text(item['status'])}</td><td>{_text(segments)}{evidence}</td>"
                    f"<td>{_text(item['reason'])}</td></tr>")
    return ("<details class='episode-coverage'><summary>Episode coverage</summary>"
            "<table><thead><tr><th>Episode</th><th>Outcome</th><th>Cut</th><th>Reason</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></details>")


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
          <div class="queue-head"><h2>Ranked cuts</h2><span id="progress">0 of {cut_count} reviewed</span>
            <progress id="review-progress" max="{cut_count}" value="0" aria-label="Cuts reviewed"></progress></div>
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
      <span class="mark" aria-hidden="true"></span><span>Promo Finder</span><span class="brand-section">Review studio</span></div>{export}</div></header>
      <main class="wrap" id="main"><div class="heading"><div><p class="overline">Screenplay review</p>
        <h1>{_text(show)}</h1><div class="stats"><span>{_text(episode_label)}</span>
        <span>{_text(cue_label)}</span><span>{count_label}</span></div></div>{run_details}</div>
        <noscript><p>All cuts are listed below. Enable JavaScript to save decisions and export your review.</p></noscript>
        <p id="notice" class="notice" role="status"></p>{body}{_coverage(result.get("coverage"))}</main>
      <script>{_JS}</script></body></html>"""


_CSS = """
:root {
 color-scheme:dark;
 --canvas:#100e12;--panel:#19161b;--well:#211d24;--ink:#fff6ed;--muted:#c0b1b9;
 --rule:#3b323b;--accent:#ffa36d;--accent-ink:#23130e;--selected:#30211f;
 font:16px/1.52 -apple-system,BlinkMacSystemFont,"Avenir Next","Segoe UI",sans-serif;
}
* {box-sizing:border-box}
body {margin:0;background:radial-gradient(ellipse 70% 420px at 36% 0,#27191e 0,transparent 100%),var(--canvas);color:var(--ink)}
.wrap {width:min(1360px,calc(100% - 80px));margin-inline:auto}
h1,h2,h3,p,blockquote,ol {margin:0}
a {color:inherit} button,a,summary {touch-action:manipulation}
button,summary {font:inherit;cursor:pointer}
:focus-visible {outline:2px solid var(--accent);outline-offset:4px}
.skip {position:absolute;top:-100px;left:12px;z-index:5;padding:8px 14px;background:var(--well)}
.skip:focus {top:8px}
.banner {border-bottom:1px solid var(--rule);background:#140f14}
.banner-inner {min-height:68px;display:flex;align-items:center;justify-content:space-between;gap:12px}
.brand {display:flex;align-items:center;gap:12px;font-weight:750;letter-spacing:-.025em}
.brand-section {padding-left:12px;border-left:1px solid var(--rule);color:var(--muted);font-size:.84rem;font-weight:500}
.mark {width:32px;height:32px;display:inline-grid;place-items:center;background:var(--accent);border-radius:9px}
.mark:after {content:"";width:15px;height:15px;background:var(--accent-ink);clip-path:polygon(0 0, 100% 50%, 0 100%, 29% 50%)}
.export {align-items:center;min-height:40px;border:1px solid var(--accent);background:var(--accent);color:var(--accent-ink);border-radius:999px;padding:6px 16px;font-size:.84rem;font-weight:750}
.export:hover {background:#ffc2a0}
.heading {padding:34px 0 24px;display:flex;justify-content:space-between;gap:24px;align-items:flex-end}
.overline,.queue-meta,.queue-head span,.method,.stats,.run-details {color:var(--muted);font-size:.83rem}
.overline {margin-bottom:6px;color:var(--accent);font-weight:650}
h1 {font:500 clamp(1.9rem,4.2vw,3.8rem)/1.05 "Iowan Old Style",Georgia,serif;letter-spacing:-.047em;overflow-wrap:anywhere}
.stats,.cut-meta {display:flex;gap:6px 12px;flex-wrap:wrap;align-items:center;font-variant-numeric:tabular-nums}
.stats {margin-top:13px}.stats span+span:before {content:"·";padding-right:12px;color:var(--accent)}
.run-details {flex:none;text-align:right}.run-details p {padding-top:8px}
summary {font-weight:650}
.workspace {display:grid;grid-template-columns:minmax(230px, 25%) minmax(0,1fr);gap:20px;align-items:start}
.queue,.cut,.empty,.episode-coverage {background:var(--panel);border:1px solid var(--rule);border-radius:18px}
.queue {position:sticky;top:16px;overflow:hidden}
.queue-head {display:grid;grid-template-columns:1fr auto;align-items:center;gap:7px;padding:16px}
.queue-head h2,.empty h2 {font-size:1rem;letter-spacing:-.025em}
.queue-head span {font-variant-numeric:tabular-nums}
.queue-head progress {grid-column:1/-1;display:block;width:100%;height:4px;border:0;border-radius:99px;overflow:hidden;background:var(--rule);color:var(--accent);accent-color:var(--accent)}
progress::-webkit-progress-bar {background:var(--rule)} progress::-webkit-progress-value {background:var(--accent)}
.queue ol {list-style:none;padding:0;max-height:min(70vh, 710px);overflow-y:auto;overscroll-behavior:contain}
.queue li {border-top:1px solid var(--rule)}
.queue-link {display:grid;grid-template-columns:34px minmax(0,1fr);align-items:start;gap:10px;padding:12px 13px;text-decoration:none;border-left:3px solid transparent}
.queue-link:hover {background:var(--well)}
.queue-link[aria-current="true"] {border-left-color:var(--accent);background:var(--selected)}
.queue-link:focus-visible {outline-offset:-3px}
.rank {display:grid;place-items:center;min-height:32px;border:1px solid var(--rule);border-radius:7px;font:600 .84rem/1 ui-monospace,monospace;color:var(--muted)}
.queue-link[aria-current="true"] .rank {background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.queue-copy {display:grid;gap:2px}
.queue-hook {font-size:.88rem;line-height:1.36;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;overflow-wrap:anywhere}
.queue-decision {width:fit-content;color:var(--accent);font-size:.72rem;font-weight:700}
.cut {margin-bottom:16px;scroll-margin-top:12px}
.screening {display:grid;grid-template-columns:minmax(195px,37%) minmax(0,1fr);border-bottom:1px solid var(--rule);border-radius:inherit}
.stage {position:relative;isolation:isolate;display:grid;place-items:center;padding:22px;min-width:0;border-radius:17px 0 0 0;overflow:hidden;
 background:radial-gradient(ellipse at 58% 40%,#653126 0,#301c23 41%,#19131b 80%)}
.stage::before {content:"";position:absolute;inset:0;z-index:-1;background:
 repeating-linear-gradient(0deg,transparent 0 3px,#fff1 4px,transparent 5px),
 linear-gradient(128deg,transparent 26%,#faa05b29 31%,transparent 37%,#b44a3023 48%,transparent 72%);opacity:.62}
.frame {position:relative;display:flex;flex-direction:column;justify-content:space-between;gap:12px;width:min(100%,220px);
 aspect-ratio:9/16;min-height:0;padding:15px;border-radius:16px;border:1px solid #a36c58;
 background:radial-gradient(ellipse at 78% 17%,#873f2c 0,transparent 60%),linear-gradient(162deg,#52273a,#231822 60%,#151118);
 box-shadow:0 22px 55px #10090cbb,inset 0 0 0 4px #150d143b}
.frame-meta {display:flex;justify-content:space-between;gap:4px;color:#fae0d3;font:600 .66rem/1.2 ui-monospace,monospace;letter-spacing:.03em}
.frame-opening {min-height:0;overflow:auto;scrollbar-width:thin;padding:3px}
.frame-opening p {margin-bottom:8px;color:#ffb992;font-size:.72rem;font-weight:700}
.frame-opening blockquote {font:500 clamp(1.05rem,1.65vw,1.4rem)/1.2 "Iowan Old Style",Georgia,serif;white-space:pre-line;overflow-wrap:anywhere}
.frame-opening.compact blockquote {font-size:1.1rem;line-height:1.27}
.editor {min-width:0;padding:clamp(18px,3vw,36px)}
.cut-meta {color:var(--muted);font-size:.82rem}
.cut-meta>span:first-child {font-weight:750;color:var(--accent)}
.placement {padding:3px 9px;border:1px solid #6a4840;border-radius:30px;color:#ffc7a9;margin-left:auto}
.hook-label {color:var(--muted);font-size:.77rem;margin-top:16px}
.cut-title {margin:4px 0 16px;font:500 clamp(1.5rem,3.1vw,2.75rem)/1.04 "Iowan Old Style",Georgia,serif;letter-spacing:-.033em;overflow-wrap:anywhere}
.cut-notes {padding:clamp(16px,2.7vw,30px)}
.timings {width:100%;border-collapse:collapse;margin:0 0 21px;background:var(--well);font-variant-numeric:tabular-nums}
.timings caption {text-align:left;font-weight:700;font-size:.93rem;margin-bottom:8px}
.timings caption span {float:right;color:var(--accent);font:600 .8rem/1.5 ui-monospace,monospace}
.timings th,.timings td {padding:7px 12px;text-align:left;border-bottom:1px solid var(--rule);overflow-wrap:anywhere}
.timings th {font-size:.79rem;color:var(--muted);font-weight:550}
.timings td {font-family:ui-monospace,monospace;font-size:.81rem}
.evidence {border-left:2px solid var(--accent);padding-left:13px;margin-bottom:18px}
h3 {font-size:.88rem;font-weight:700}
.evidence blockquote,.reason p,.spoiler p {margin-top:3px;overflow-wrap:anywhere}
.evidence blockquote,.reason p {color:var(--muted);font-size:.91rem;white-space:pre-line}
.reason h3:not(:first-child) {margin-top:12px}
.spoiler {margin-top:10px;border:1px solid var(--rule);border-radius:9px;background:var(--well)}
.spoiler summary {color:var(--accent);padding:10px 12px;font-size:.88rem;display:list-item}
.spoiler p {padding:0 12px 12px;color:var(--muted)}
.review-tools {flex-direction:column;align-items:flex-start;margin-top:18px;padding-top:13px;border-top:1px solid var(--rule)}
.decisions {display:flex;flex-wrap:wrap;gap:6px;margin-top:7px}
.decisions button {min-height:40px;border:1px solid #665261;border-radius:999px;background:var(--well);padding:4px 17px;color:var(--ink);font-size:.86rem;font-weight:680}
.decisions button:hover {background:#3a2c39}
.decisions button[aria-pressed="true"] {background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.method {margin-top:16px;overflow-wrap:anywhere}.method strong {color:var(--ink);font-weight:550}
.decision-status {color:var(--accent);font-size:.79rem;margin-top:6px}
.decision-status:empty {display:none}
.stranger {background:var(--well);border:1px solid var(--rule);border-radius:9px;padding:12px 14px;margin:14px 0}.stranger p {margin-top:4px}
.grades {color:var(--muted);font-size:.84rem}
.script {white-space:pre-wrap;overflow-wrap:anywhere;font: .8rem/1.55 ui-monospace,monospace;max-height:40vh;overflow:auto;padding:0 12px 12px}
.episode-coverage {padding:13px 16px;margin:8px 0 28px;overflow:auto}
.episode-coverage table {width:100%;border-collapse:collapse;text-align:left}
.episode-coverage th,.episode-coverage td {padding:8px;border-bottom:1px solid var(--rule);vertical-align:top}
.episode-coverage td p {margin:6px 0}
.empty {padding:26px}.empty p {margin-top:6px}
.notice {font-size:.85rem;color:var(--accent);margin-bottom:8px}.notice:empty {display:none}
[hidden],.js-only {display:none!important}.ready .js-only {display:flex!important}
@media (max-width:1020px) {.wrap {width:calc(100% - 40px)}.workspace {gap:12px}.stage {padding:15px}}
@media (max-width:800px) {
 .wrap {width:calc(100% - 28px)}.workspace {grid-template-columns:minmax(0,1fr)}
 .queue {position:static}.queue ol {max-height:164px}
 .heading {padding:20px 0;align-items:start;flex-direction:column;gap:10px}
 .run-details {text-align:left}.queue-head {padding:10px 13px;display:grid}
 .queue-link {padding:8px 11px}.cut {scroll-margin-top:8px}
}
@media (max-width:520px) {
 .screening {grid-template-columns:1fr}
 .stage {min-height:220px;border-radius:17px 17px 0 0}
 .frame {width:min(100%,220px);background-position:center}
 .brand-section {display:none}.brand {gap:8px}
 .mark {width:26px;height:26px}.export {padding-inline:10px;font-size:.76rem}
}
@media print {
 :root {color-scheme:light;--ink:#15131a;--muted:#44404a;--canvas:white;--panel:white;--well:#fafafa;--rule:#ddd;--accent:#933a13}
 body {background:white}
 .banner,.queue,:root.ready .review-tools,.export,.spoiler,.run-details,.notice {display:none!important}
 .workspace {display:block}.cut[hidden] {display:block!important}.wrap {width:100%}.cut {break-inside:avoid}.heading {padding-top:0}
 .screening {display:block}.stage,.frame {background:white;color:var(--ink);box-shadow:none;border:0}
 .stage::before {display:none}.frame {width:auto;aspect-ratio:auto}.frame-meta,.frame-opening p {color:var(--muted)}
 .placement {color:var(--accent)}
}
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
    document.getElementById("review-progress").value = count;
  }

  function select(index) {
    articles.forEach((article, i) => {
      article.hidden = i !== index;
      if (i === index) links[i].setAttribute("aria-current", "true");
      else links[i].removeAttribute("aria-current");
    });
    const queue = links[index].closest("ol");
    const selected = links[index].getBoundingClientRect();
    const bounds = queue.getBoundingClientRect();
    if (selected.top < bounds.top) queue.scrollTop += selected.top - bounds.top;
    else if (selected.bottom > bounds.bottom) queue.scrollTop += selected.bottom - bounds.bottom;
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
      if (window === window.top && location.hash !== link.hash) history.pushState(null, "", link.hash);
      articles[index].querySelector("h2").focus({preventScroll:true});
      const cut = articles[index];
      if (matchMedia("(max-width:800px)").matches || cut.getBoundingClientRect().top < 0) cut.scrollIntoView();
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
    const article = button.closest(".cut");
    const index = article.dataset.index;
    const choice = button.dataset.decision;
    if (choices[index] === choice) delete choices[index];
    else choices[index] = choice;
    try { localStorage.setItem(key, JSON.stringify(choices)); }
    catch (_) { canSave = false; }
    applyDecisions();
    const status = choices[index] ? choices[index] : "unreviewed";
    article.querySelector(".decision-status").textContent = "Rank " + article.dataset.rank + " marked " + status + ".";
    if (!canSave) document.getElementById("notice").textContent = "Browser storage unavailable. Export a CSV to keep decisions.";
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
