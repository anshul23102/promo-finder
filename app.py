"""Promo Finder web app: upload screenplays, get ranked promos an editor can act on.

    streamlit run app.py

Works on Hugging Face Spaces or Streamlit Community Cloud. Set GEMINI_API_KEY (or another
provider's key) as a secret, or paste a key in the sidebar for this session only.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import zipfile
from uuid import uuid4

import streamlit as st

from promo import run
from promo.llm import PRESETS, load_dotenv

load_dotenv()
st.set_page_config(page_title="Promo Finder", page_icon="🎬", layout="wide")
st.html("""
<style>
.finder-intro {
    position: relative;
    isolation: isolate;
    overflow: hidden;
    margin-bottom: 1.2rem;
    padding: clamp(1.35rem, 4vw, 3rem);
    border: 1px solid #543640;
    border-radius: 18px;
    background: radial-gradient(ellipse at 90% 0%, #673527, transparent 62%), #221721;
}
.finder-intro::after {
    content: "";
    position: absolute;
    z-index: -1;
    inset: 0;
    background: repeating-linear-gradient(0deg, transparent 0 5px, #ffc4a108 6px, transparent 7px);
    pointer-events: none;
}
.finder-intro .studio { color: #ffa36d; font-size: .83rem; font-weight: 700; margin-bottom: .2rem; }
.finder-intro h1 {
    padding: 0;
    font: 500 clamp(2.6rem, 6vw, 5rem)/1 "Iowan Old Style", Georgia, serif;
    letter-spacing: -.05em;
}
.finder-intro .intro-copy { max-width: 34rem; color: #e2ced7; margin: .8rem 0 0; }
</style>
<section class="finder-intro" aria-labelledby="finder-title">
    <p class="studio">Microdrama review studio</p>
    <h1 id="finder-title">Promo Finder</h1>
    <p class="intro-copy">Find 20–60 second promos in a timed screenplay. Review each opening, cliffhanger and source timecode before you send a cut to edit.</p>
</section>
""")

available_providers = ["gemini", "groq", "openrouter", "openai"]
with st.sidebar:
    st.header("Model")
    provider = st.selectbox("Editor model", ["rules", *available_providers],
                            help="Rules mode runs without API access. Use the CLI for Ollama or a custom endpoint.")
    name = st.text_input("Model name (blank = default)",
                         value="", placeholder=(PRESETS.get(provider, (None, None, ""))[2] or ""))
    judge = st.text_input("Judge model (blank = same)", placeholder="e.g. gemini:gemini-flash-lite-latest or groq")
    if provider != "rules":
        st.caption("AI mode sends screenplay text to your model provider. Use material permitted by its terms. Google’s unpaid Gemini API terms say not to submit confidential information.")
    key_var = PRESETS.get(provider, (None, None))[1]
    typed_key = None
    if key_var:
        typed_key = st.text_input(f"Your {key_var}", type="password",
                                  help="Used for this run only. It is never saved, logged or shared with other visitors.") or None
        st.caption("Key ready." if (typed_key or os.environ.get(key_var)) else "Paste a key, or use the 'rules' model or the demo, which need none.")
    st.header("Scope")
    episodes = st.text_input("Episodes (blank = all)", placeholder="e.g. 1-10")
    rounds = st.slider("Ranking rounds", 1, 6, 4)
    fast = st.checkbox("Skip the rules-vs-AI ablation (fewer calls)", value=False)

DEMO = Path(__file__).parent / "examples" / "last-edition"
uploads = st.file_uploader("Screenplays: one ZIP, or several .txt episodes", type=["zip", "txt"], accept_multiple_files=True)
demo = st.checkbox("No file? Use the built-in demo (two original, made-up episodes)", value=False)

if st.button("Find promos", type="primary", disabled=not (uploads or demo) or bool(key_var and not (typed_key or os.environ.get(key_var)))):
    if "workspace" not in st.session_state:
        st.session_state["workspace"] = tempfile.TemporaryDirectory(prefix="promo-")
    workspace = Path(st.session_state["workspace"].name)
    st.session_state.pop("out", None)
    status = st.status("Working ...", expanded=True)
    try:
        if judge and judge.partition(":")[0] not in available_providers:
            raise ValueError("Choose a supported hosted judge provider or leave it blank.")
        if len({f.name.casefold() for f in uploads}) != len(uploads):
            raise ValueError("Each uploaded file needs a unique name.")
        if any(f.name.lower().endswith(".zip") for f in uploads) and len(uploads) != 1:
            raise ValueError("Upload a single ZIP or a set of TXT files.")
        out = workspace / uuid4().hex
        with tempfile.TemporaryDirectory(dir=workspace, prefix="input-") as upload_dir:
            work = Path(upload_dir)
            if demo and not uploads:
                source = DEMO
            elif uploads[0].name.lower().endswith(".zip"):
                source = work / "input.zip"
                source.write_bytes(uploads[0].getvalue())
            else:
                source = work
                for f in uploads:
                    (source / Path(f.name).name).write_bytes(f.getvalue())
            argv = [str(source), "--model", provider if not name or provider == "rules" else f"{provider}:{name}",
                    "--out", str(out), "--cache", str(workspace / "cache"), "--rounds", str(rounds),
                    "--title", Path(uploads[0].name).stem if uploads else "Demo: The Last Edition"]
            if judge:
                argv += ["--judge", judge]
            if episodes:
                argv += ["--episodes", episodes]
            if fast:
                argv += ["--no-rules-check"]
            run.main(argv, key=typed_key, log_fn=status.write)
        st.session_state["out"] = str(out)
        status.update(label="Done", state="complete")
    except Exception as exc:
        status.update(label="Stopped", state="error")
        st.error(f"{exc}\n\nCompleted model calls can be reused when you retry in this browser session.")

if "out" in st.session_state and Path(st.session_state["out"]).is_dir():
    out = Path(st.session_state["out"])
    data = json.loads((out / "promos.json").read_text())
    summary = data["summary"]
    a, b, c, d = st.columns(4)
    a.metric("Episodes", summary["episodes"])
    b.metric("Candidates", summary["candidates"])
    c.metric("Timing-checked" if summary["judge_model"] == "none" else "Viewer shortlist", summary["passed"])
    d.metric("Rule violations", summary["rule_violations"])
    tab_review, tab_plan, tab_coverage, tab_quality, tab_files = st.tabs(
        ["Review clips", "Posting plan", "Episode coverage", "Quality", "Download"]
    )
    with tab_plan:
        rows = [{"#": p["rank"], "slot": p["plan"], "segments": "; ".join(f"E{s['episode']} {s['start']}-{s['end']}" for s in p["segments"]),
                 "sec": p["duration_s"], "hook": p["hook"], "cliffhanger": p["cliffhanger"], "why": p["why"]}
                for p in data["promos"]]
        st.dataframe(rows, width="stretch", hide_index=True)
    with tab_review:
        st.components.v1.html((out / "index.html").read_text(), height=1100, scrolling=True)
    with tab_coverage:
        coverage = json.loads((out / "coverage.json").read_text())
        st.dataframe([
            {"Episode": row["episode"], "Outcome": row["status"], "Reason": row["reason"],
             "Cut": " / ".join(f"{s['start']}–{s['end']}" for s in (row["cut"] or {}).get("segments", []))}
            for row in coverage
        ], width="stretch", hide_index=True)
        st.caption("Open Episode coverage below the review queue to inspect script evidence.")
    with tab_quality:
        st.markdown((out / "evaluation.md").read_text())
    with tab_files:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(out.iterdir()):
                z.write(f, f.name)
        st.download_button("Download all outputs (ZIP)", buffer.getvalue(), "promo-finder-run.zip")
        st.download_button("Cut list for Premiere / Resolve (EDL)", (out / "cutlist.edl").read_bytes(), "cutlist.edl")
