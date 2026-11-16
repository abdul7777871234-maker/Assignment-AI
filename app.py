from __future__ import annotations
import time
from io import BytesIO
import re
import streamlit as st
from docx import Document
from ai_engine import stream_answer
from document_parser import extract_text
from security_store import SecureUploadStore, start_cleanup_scheduler

APP_NAME = "University Assignment AI"
MAX_FILE_BYTES = 50 * 1024 * 1024
st.set_page_config(page_title=APP_NAME, page_icon="🎓", layout="wide")

def build_docx_bytes(title: str, markdown_text: str) -> bytes:
    """Render an assistant answer as a formatted Word document, including Markdown tables."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
    from docx.shared import Inches, Pt, RGBColor
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.8)
    section.right_margin = Inches(0.8)
    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)
    normal.font.color.rgb = RGBColor(35, 35, 35)
    normal.paragraph_format.space_after = Pt(6)
    for style_name in ("Heading 1", "Heading 2", "Heading 3"):
        style = doc.styles[style_name]
        style.font.name = "Times New Roman"
        style.font.color.rgb = RGBColor(48, 44, 92)
        style.font.bold = True
    doc.core_properties.title = title

    title_p = doc.add_paragraph()
    title_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title_run = title_p.add_run(title)
    title_run.bold = True
    title_run.font.name = "Times New Roman"
    title_run.font.size = Pt(18)
    title_run.font.color.rgb = RGBColor(48, 44, 92)
    title_p.paragraph_format.space_after = Pt(16)

    def add_inline(paragraph, text):
        pattern = re.compile(r"(\*\*.*?\*\*|\*[^*]+\*)")
        pos = 0
        for match in pattern.finditer(text):
            if match.start() > pos:
                paragraph.add_run(text[pos:match.start()])
            token = match.group(0)
            run = paragraph.add_run(token[2:-2] if token.startswith("**") else token[1:-1])
            if token.startswith("**"):
                run.bold = True
            else:
                run.italic = True
            pos = match.end()
        if pos < len(text):
            paragraph.add_run(text[pos:])

    def cell_shading(cell, fill):
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:fill"), fill)
        tc_pr.append(shd)

    def add_markdown_table(rows):
        parsed = []
        for row in rows:
            cells = [part.strip() for part in row.strip().strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
                continue
            parsed.append(cells)
        if not parsed:
            return
        width = max(len(row) for row in parsed)
        table = doc.add_table(rows=0, cols=width)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"
        for row_index, values in enumerate(parsed):
            cells = table.add_row().cells
            for col_index in range(width):
                cell = cells[col_index]
                cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
                value = values[col_index] if col_index < len(values) else ""
                cell.text = ""
                p = cell.paragraphs[0]
                add_inline(p, value.replace(r"\(", "").replace(r"\)", ""))
                for run in p.runs:
                    run.font.name = "Times New Roman"
                    run.font.size = Pt(10)
                    if row_index == 0:
                        run.bold = True
                        run.font.color.rgb = RGBColor(255, 255, 255)
                if row_index == 0:
                    cell_shading(cell, "302C5C")
                elif row_index % 2 == 0:
                    cell_shading(cell, "F0EEF7")
        doc.add_paragraph()

    lines = markdown_text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped or stripped in {"---", "***", "___", r"\1", r"\\1"}:
            i += 1
            continue
        if stripped.startswith("|") and "|" in stripped[1:]:
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            add_markdown_table(table_lines)
            continue
        if stripped.startswith("### "):
            p = doc.add_heading(level=3)
            add_inline(p, stripped[4:])
        elif stripped.startswith("## "):
            p = doc.add_heading(level=2)
            add_inline(p, stripped[3:])
        elif stripped.startswith("# "):
            p = doc.add_heading(level=1)
            add_inline(p, stripped[2:])
        elif stripped.startswith(("- ", "* ", "• ")):
            p = doc.add_paragraph(style="List Bullet")
            add_inline(p, stripped[2:])
        elif re.match(r"^\d+[.)]\s+", stripped):
            p = doc.add_paragraph(style="List Number")
            add_inline(p, re.sub(r"^\d+[.)]\s+", "", stripped))
        else:
            clean = stripped.replace(r"\(", "").replace(r"\)", "").replace(r"\[", "").replace(r"\]", "")
            if clean and not clean.lower().startswith(("note: i can provide the solution in text format", "i am unable to generate a word file")):
                p = doc.add_paragraph()
                add_inline(p, clean)
        i += 1

    footer = section.footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    fr = footer.add_run("University Assignment AI")
    fr.font.name = "Times New Roman"
    fr.font.size = Pt(9)
    fr.font.color.rgb = RGBColor(120, 120, 120)
    buffer = BytesIO()
    doc.save(buffer)
    return buffer.getvalue()

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
for key, default in [("messages", []), ("uploads", {}), ("pending_upload_ids", [])]:
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
.block-container { max-width: 1120px; padding-top: 3.5rem; }
.brand { display: block; overflow: visible; margin: 0 0 .35rem; padding-top: .15rem; font-size: 2rem; font-weight: 800; line-height: 1.3; letter-spacing: -.04em; color: #F5F0FF; }
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
    task = st.radio("Workspace", ["Assignment", "MCQs", "Humanize"], index=0)
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
        store.delete_all(list(st.session_state.uploads.keys()))
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
        if msg["role"] == "assistant" and msg["content"] and not msg["content"].startswith("Generation error:"):
            docx_data = build_docx_bytes("University Assignment AI - Solution", msg["content"])
            st.download_button(
                "Download as Word (.docx)",
                data=docx_data,
                file_name=f"assignment_solution_{st.session_state.messages.index(msg) + 1}.docx",
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                key=f"download_docx_{st.session_state.messages.index(msg)}",
                use_container_width=False,
            )

prompt = st.chat_input(
    "Message University Assignment AI…",
    accept_file="multiple",
    file_type=["pdf", "docx", "txt", "md", "rtf", "pptx", "xlsx", "csv", "png", "jpg", "jpeg", "webp"],
    max_upload_size=50,
)
if prompt:
    incoming = getattr(prompt, "files", []) or []
    for uploaded in incoming:
        raw = uploaded.getvalue()
        if len(raw) > MAX_FILE_BYTES:
            st.error(f"{uploaded.name}: file exceeds the 50 MB limit.")
            continue
        try:
            meta = store.save(raw, uploaded.name)
            st.session_state.uploads[meta["id"]] = meta
            st.session_state.pending_upload_ids.append(meta["id"])
            st.success(f"Encrypted upload added: {meta['name']}")
        except Exception as exc:
            st.error(f"Could not securely store {uploaded.name}: {exc}")

    user_text = (getattr(prompt, "text", "") or "").strip()
    if incoming and not user_text:
        st.rerun()
    if user_text:
        st.session_state.messages.append({"role": "user", "content": user_text})
        with st.chat_message("user"):
            st.markdown(user_text)
        refs = []
        pending_ids = list(st.session_state.pending_upload_ids)
        has_new_attachments = bool(pending_ids)
        for fid in pending_ids:
            meta = st.session_state.uploads.get(fid)
            if not meta:
                continue
            try:
                raw = store.read(fid)
                extracted = extract_text(meta["name"], raw)
                del raw
                if extracted and extracted.strip():
                    refs.append(f"FILE: {meta['name']}\n{extracted}")
                else:
                    st.warning(f"{meta['name']}: no readable text was extracted from this file.")
            except Exception as exc:
                st.warning(f"{meta['name']}: {exc}")
                store.delete(fid)
                st.session_state.uploads.pop(fid, None)
        st.session_state.pending_upload_ids = []
        context = "\n\n---\n\n".join(refs)[:120000]
        with st.chat_message("assistant"):
            placeholder = st.empty()
            answer = ""
            try:
                if has_new_attachments and not context.strip():
                    answer = "I couldn't extract readable text from the newly uploaded file. Please upload a text-based PDF/DOCX or a clear image, or check whether the file is scanned or password-protected."
                    placeholder.warning(answer)
                else:
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
st.caption("Text extraction: PDF, DOCX, TXT, Markdown, RTF, PPTX, XLSX, CSV and common images. OCR requires Tesseract on the server. Maximum file size: 50 MB per file.")
st.caption("30-minute expiry applies to uploaded source files and temporary processing copies. Generated chat responses remain until the chat is cleared or the session ends.")
