# University Assignment AI

Streamlit academic writing assistant with Groq-first streaming, Gemini fallback, document extraction, and encrypted temporary uploads.

## Features
- Chat-first interface with file attachment control.
- Humanize, Deep Rewrite, and Assignment modes.
- Groq primary provider and Gemini fallback.
- Streaming model output.
- PDF, DOCX, TXT, Markdown, RTF, PPTX, XLSX, CSV and image OCR extraction.
- Fernet encryption at rest for uploaded files.
- Manual deletion and 30-minute expiry.
- 25 MB per-file upload limit.

## Local setup
1. Use Python 3.11 or newer.
2. Install dependencies: pip install -r requirements.txt
3. Generate an encryption key:
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
4. Create .streamlit/secrets.toml with:
   UPLOAD_ENCRYPTION_KEY = "YOUR_GENERATED_FERNET_KEY"
   GROQ_API_KEY = "YOUR_GROQ_KEY"
   GROQ_MODEL = "llama-3.3-70b-versatile"
   GEMINI_API_KEY = "YOUR_GEMINI_KEY"
   GEMINI_MODEL = "gemini-2.5-flash"
5. Run: streamlit run app.py

At least one AI provider key is required. Set secrets in the hosting platform's secret manager. Never commit secrets.toml or API keys.

## Upload security and 30-minute deletion
- Uploaded bytes are encrypted before being written to the private upload directory.
- The encryption key is read from Streamlit Secrets and is not stored in the repository.
- TTL is 30 minutes. Expiry is checked on every app rerun and before every file read. A background worker scans every 60 seconds.
- Each uploaded file has a Delete control. The sidebar also offers Delete all uploaded files.
- Extracted text is held only in request memory and discarded after the AI call. It is not written to the upload directory or added to chat history.
- Default upload directory: /tmp/university-assignment-ai-uploads. Set UAAI_UPLOAD_DIR to a private temporary volume if required.

## Deployment limitations
The in-process scheduler is appropriate only for a single Streamlit process. Multi-replica deployments require a shared encrypted object store and an external scheduled cleanup job covering every replica. Ephemeral hosts may delete files earlier on restart.

Deleting a file removes its encrypted application copy. It cannot guarantee immediate erasure from filesystem snapshots, provider backups, hosting logs, crash dumps, or AI provider infrastructure. Review provider retention terms. Avoid uploading highly sensitive personal, financial, or identity documents.

The 30-minute TTL applies to uploaded source files and temporary processing copies. Generated answers may quote uploaded content and remain in the current chat session until cleared or the session ends.

## OCR
Image OCR requires the Tesseract executable on the host in addition to pytesseract. Scanned PDFs currently need OCR preprocessing; text-based PDFs are supported directly.

## Security notes
- Never commit .streamlit/secrets.toml, API keys, or the Fernet key.
- Use HTTPS and restrict app access for private coursework.
- Rotate the encryption key only after deleting or migrating still-needed encrypted uploads; old files cannot be decrypted with a new key.
