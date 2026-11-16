from __future__ import annotations
import time
import streamlit as st
from ai_engine import stream_answer
from document_parser import extract_text
from security_store import SecureUploadStore, start_cleanup_scheduler

APP_NAME = "University Assignment AI"
MAX_FILE_BYTES = 25 * 1024 * 1024
st.set_page_config(page_title=APP_NAME, page_icon="🎓", layout="wide")

def get_store():
    key = st.secrets.get("UPLOAD_ENCRYPTION_KEY", "")
    if not key:
        st.error("Backend encryption is not configured. Add UPLOAD_ENCRYPTION_KEY to Streamlit Secrets.")
        st.stop()
    store = SecureUploadStore(str(key))
    store.cleanup_expired()
    start_cleanup_scheduler(store)
    return store

store = get_store()
for key, default in [("messages", []), ("uploads", {})]:
    if key not in st.session_state:
        st.session_state[key] = default

now = time.time()
for fid, meta in list(st.session_state.uploads.items()):
    if now >= meta["expires_at"]:
        store.delete(fid)
        st.session_state.uploads.pop(fid, None)

st.markdown("""
<style>
.stApp { background: radial-gradient(ellipse at 15% 0%, #261744 0%, #100B1C 48%, #0B0812 100%); }
.block-container { max-width: 1120px; padding-top: 1.5rem; }
.brand { font-size: 2rem; font-weight: 800; letter-spacing: -.04em; color: #F5F0FF; }
.brand span { color: #B69CFF; }
.subtle { color: #B7A9CC; }
div[data-testid="stChatMessage"] { border: 1px solid rgba(190,160,255,.12); border-radius: 16px; background: rgba(31,21,49,.66); }
div[data-testid="stChatInput"] { border: 1px solid #7052A8; border-radius: 18px; background: #1B1230; }
.stButton > button { border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown(f"### 🎓 {APP_NAME}")
    st.caption("Your academic writing and study workspace")
    st.divider()
    task = st.radio("Workspace", ["Chat", "Humanize", "Deep Rewrite", "Assignment"])
    st.divider()
    st.markdown("**AI providers**")
    st.write(("🟢" if st.secrets.get("GROQ_API_KEY", "") else "⚪") + " Groq")
    st.write(("🟢" if st.secrets.get("GEMINI_API_KEY", "") else "⚪") + " Gemini")
    st.caption("Groq is tried first. Gemini is the fallback.")
    st.divider()
    st.caption("Uploads are encrypted at rest and expire after 30 minutes.")
    if st.button("Clear chat", use_container_width=True):
        st.session_state.messages = []
        st.rerun()
    if st.button("Delete all uploaded files", use_container_width=True):
        store.delete_all()
        st.session_state.uploads = {}
        st.success("All current-session uploads deleted.")
        st.rerun()

st.markdown(f'<div class="brand">University <span>Assignment AI</span></div>', unsafe_allow_html=True)
st.markdown('<p class="subtle">Ask questions, improve your writing, and work through assignments with AI.</p>', unsafe_allow_html=True)

if st.session_state.uploads:
    with st.expander(f"Attached files ({len(st.session_state.uploads)})", expanded=True):
        for fid, meta in list(st.session_state.uploads.items()):
            a, b, c = st.columns([5, 2, 1])
            a.write("📄 " + meta["name"])
            remaining = max(0, int(meta["expires_at"] - time.time()))
            b.caption(f"Deletes in {remaining // 60:02d}:{remaining % 60:02d}")
            if c.button("Delete", key=f"delete_{fid}"):
                store.delete(fid)
                st.session_state.uploads.pop(fid, None)
                st.rerun()

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input(
    "Message University Assignment AI…",
    accept_file="multiple",
    file_type=["pdf", "docx", "txt", "md", "rtf", "pptx", "xlsx", "csv", "png", "jpg", "jpeg", "webp"],
    max_upload_size=25,
)
if prompt:
    incoming = getattr(prompt, "files", []) or []
    for uploaded in incoming:
        raw = uploaded.getvalue()
        if len(raw) > MAX_FILE_BYTES:
            st.error(f"{uploaded.name}: file exceeds the 25 MB limit.")
            continue
        try:
            meta = store.save(raw, uploaded.name)
            st.session_state.uploads[meta["id"]] = meta
            st.success(f"Encrypted upload added: {meta['name']}")
        except Exception as exc:
            st.error(f"Could not securely store {uploaded.name}: {exc}")

    user_text = (getattr(prompt, "text", "") or "").strip()
    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})
        with st.chat_message("user"):
            st.markdown(user_text)
        refs = []
        for fid, meta in list(st.session_state.uploads.items()):
            try:
                raw = store.read(fid)
                refs.append(f"FILE: {meta['name']}\\n" + extract_text(meta["name"], raw))
                del raw
            except Exception as exc:
                st.warning(f"{meta['name']}: {exc}")
                store.delete(fid)
                st.session_state.uploads.pop(fid, None)
        context = "\\n\\n---\\n\\n".join(refs)[:120000]
        with st.chat_message("assistant"):
            placeholder = st.empty()
            answer = ""
            try:
                for piece in stream_answer(st.secrets, st.session_state.messages, task, attached_text=context):
                    answer += piece
                    placeholder.markdown(answer + "▌")
                placeholder.markdown(answer)
            except Exception as exc:
                answer = f"Generation error: {type(exc).__name__}: {exc}"
                placeholder.error(answer)
        st.session_state.messages.append({"role": "assistant", "content": answer})
        del context, refs
        st.rerun()

st.divider()
st.caption("Text extraction: PDF, DOCX, TXT, Markdown, RTF, PPTX, XLSX, CSV and common images. OCR requires Tesseract on the server. Maximum file size: 25 MB.")
st.caption("30-minute expiry applies to uploaded source files and temporary processing copies. Generated chat responses remain until the chat is cleared or the session ends.")
