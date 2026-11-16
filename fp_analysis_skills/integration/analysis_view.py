"""Example Streamlit view for an "Analysis" workspace (copy into the web app and adapt).

Mirrors handoff_views.render_format: same hand-off object, same output rendering and ZIP, but the
chat runs fp_analysis.agent.run_analysis_agent. Wire it up in streamlit_app.py with:

    VIEWS = ["Research", "Review & hand off", "Format", "Analysis", "Workbench"]
    ...
    if workspace == "Analysis":
        from analysis_view import render_analysis
        render_analysis()
        st.stop()
"""

from __future__ import annotations

import os

import streamlit as st

import dataset_store
from handoff_views import _render_output, _zip_name  # the app's own helpers

from fp_analysis.agent import run_analysis_agent
from fp_analysis.registry import catalog


def render_analysis() -> None:
    st.title("Analysis")
    handoff = st.session_state.get("handoff")
    if handoff is None:
        st.info("No datasets handed off yet. Fetch data in Research, then confirm them in Review & hand off.")
        return
    handoff.setdefault("outputs", {})
    with st.expander("Available analysis skills", expanded=False):
        for item in catalog():
            needs = ", ".join(item["required_indicators"]) or "team ticker table"
            st.markdown(f"**{item['title']}** (`{item['skill_id']}`, {item['stage']}) - {item['summary']}  \n"
                        f"Needs: {needs}")

    messages = st.session_state.setdefault("analysis_messages", [])
    request = st.chat_input("Which analysis? e.g. r - g for emerging markets since 2005, GDP-weighted",
                            key="analysis_chat_input")
    if request:
        messages.append({"role": "user", "content": request})
        reply = {"role": "assistant", "content": "", "path": [], "error": False}
        try:
            history = [{"role": m["role"], "content": m["content"]} for m in messages if not m.get("error")]
            with st.status("Running analysis skills...", expanded=True) as status:
                result = run_analysis_agent(
                    history, handoff,
                    model=st.session_state.get("openai_model_input", os.getenv("OPENAI_MODEL", "gpt-5.6-terra")),
                    on_tool_call=lambda name: status.write(f"Running {name.replace('_', ' ')}"),
                )
                status.update(label="Analysis complete", state="complete")
            reply.update(content=result["answer"], path=result["path"])
        except Exception as exc:
            reply.update(content=f"I couldn't complete that analysis: {exc}", error=True)
        messages.append(reply)

    for message in messages:
        with st.chat_message(message["role"]):
            (st.error if message.get("error") else st.markdown)(message["content"])
            if message.get("path"):
                with st.expander("Analysis steps", expanded=False):
                    for step in message["path"]:
                        st.markdown(f"- {step}")

    outputs = list(handoff["outputs"].values())
    if outputs:
        st.subheader("Outputs")
        for output in outputs:
            _render_output(output)
        st.download_button("Download everything (ZIP)", data=dataset_store.build_zip(handoff["datasets"], outputs),
                           file_name=_zip_name(handoff["id"]), mime="application/zip", key="analysis_zip_download")
