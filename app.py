from flask import Flask, request, jsonify, render_template_string
import os
import io
import re
import json
import docx
import pdfplumber
import requests
import mysql.connector
from datetime import datetime

# -----------------------
# Config
# -----------------------
app = Flask(__name__)

# MySQL config - you can set these env vars or replace defaults below
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "root")
DB_PASS = os.environ.get("DB_PASS", "tiger")   # change!
DB_NAME = os.environ.get("DB_NAME", "lexify_db")
DB_PORT = int(os.environ.get("DB_PORT", 3306))

# Upload folder (we keep files in memory; this is just for potential saves)
UPLOAD_FOLDER = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Gemini API (Google AI Studio)
API_KEY = os.environ.get("GOOGLE_API_KEY", "")
API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={API_KEY}"

# -----------------------
# Helper: DB connection + ensure table
# -----------------------
def get_db_connection():
    return mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        port=DB_PORT,
        charset='utf8mb4'
    )

def ensure_table_exists():
    conn = None
    try:
        # connect to server; try to create database if not exists
        conn = mysql.connector.connect(
            host=DB_HOST, user=DB_USER, password=DB_PASS, port=DB_PORT, charset='utf8mb4'
        )
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` DEFAULT CHARACTER SET 'utf8mb4'")
        conn.commit()
        cur.close()
        conn.close()

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INT AUTO_INCREMENT PRIMARY KEY,
                filename VARCHAR(255) NOT NULL,
                document_type VARCHAR(128),
                analysis_summary TEXT,
                missing_items JSON,
                risks JSON,
                content LONGTEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) CHARACTER SET = utf8mb4;
        """)
        conn.commit()
        cur.close()
    except Exception as e:
        print("Error ensuring DB/table:", e)
    finally:
        if conn:
            conn.close()

ensure_table_exists()

# -----------------------
# Frontend HTML (complete UI: upload, results, history, full report modal)
# -----------------------
HTML_CONTENT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Smart Document Scanner — Lexify</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { font-family: "Nunito Sans", "Segoe UI", Tahoma, sans-serif;}
    pre { white-space: pre-wrap; word-wrap: break-word; }
  </style>
</head>
<center>
<body class="min-h-screen p-6" style="background-color: #3E5C76;">
  <div class="max-w-5xl mx-auto">
    <div class="p-6 rounded-2xl shadow w-full max-w-2xl mx-auto" style="background-color: #F0EBD8;">
      <h1 class="text-2xl font-bold mb-2" "style=color: #0D1321;">Smart Document Scanner </h1>
      <p class="text-sm mb-4" style="color: #0D1321;">Upload a DOCX or PDF to extract text and get an AI legal analysis. Results saved to your database.</p>

      <form id="uploadForm" class="space-y-4">
        <input id="document" name="document" type="file" accept=".pdf,.docx" class="block" required />
        <div class="flex justify-center space-x-2" >
          <button id="submitBtn" type="submit" class="px-4 py-2 text-white rounded " style = "background-color:#1D2D44;">Extract & Analyze</button>
          <button id="historyBtn" type="button" class="px-4 py-2  text-white rounded" style = "background-color:#1D2D44;">View History</button>
        </div>
      </form>

      <!-- Results -->
      <div id="results" class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-6">
        <div>
          <h2 class="font-semibold " style="color: #0D1321;">Extracted Content</h2>
          <div id="contentBox" class="mt-2 p-4 bg-gray-50 border rounded max-h-64 overflow-auto text-sm text-gray-800">
            <p class=" text-center"  style="color: #748CAB;">Your extracted text will appear here.</p>
          </div>
        </div>

        <div>
          <h2 class="font-semibold "style="color: #0D1321;">AI Analysis</h2>
          <div id="analysisBox" class="mt-2 p-4 bg-gray-50 border rounded max-h-64 overflow-auto text-sm text-gray-800">
            <p class=" text-center" style="color: #748CAB;">AI analysis will appear here.</p>
          </div>
        </div>
      </div>
    </div>

    <!-- History Panel -->
    <div id="historyPanel" class="hidden mt-6 bg-white p-4 rounded shadow">
      <h3 class="font-semibold mb-2">History (latest uploads)</h3>
      <div id="historyList" class="space-y-2 text-sm"></div>
    </div>
  </div>

  <!-- Full Report Modal -->
  <div id="modal" class="fixed inset-0 bg-black bg-opacity-50 hidden items-center justify-center p-4 z-50">
    <div class="bg-white rounded-lg max-w-3xl w-full p-4">
      <div class="flex justify-between items-start">
        <h3 id="modalTitle" class="text-lg font-bold">Full Analysis</h3>
        <button id="closeModal" class="text-gray-600">Close</button>
      </div>
      <div class="mt-3 text-sm text-gray-800">
        <p><strong>Filename:</strong> <span id="modalFilename"></span></p>
        <p><strong>Document Type:</strong> <span id="modalDocType"></span></p>
        <p class="mt-2"><strong>Analysis Summary:</strong></p>
        <p id="modalSummary" class="mt-1"></p>

        <div class="mt-3">
          <strong>Missing Items</strong>
          <ul id="modalMissing" class="list-disc pl-6 mt-1"></ul>
        </div>

        <div class="mt-3">
          <strong>Risks</strong>
          <ul id="modalRisks" class="list-disc pl-6 mt-1"></ul>
        </div>

        <div class="mt-3">
          <strong>Full Extracted Content</strong>
          <pre id="modalContent" class="mt-1 bg-gray-50 p-3 rounded max-h-64 overflow-auto"></pre>
        </div>
      </div>
    </div>
  </div>

<script>
const uploadForm = document.getElementById('uploadForm');
const fileInput = document.getElementById('document');
const submitBtn = document.getElementById('submitBtn');
const contentBox = document.getElementById('contentBox');
const analysisBox = document.getElementById('analysisBox');
const historyBtn = document.getElementById('historyBtn');
const historyPanel = document.getElementById('historyPanel');
const historyList = document.getElementById('historyList');

const modal = document.getElementById('modal');
const closeModal = document.getElementById('closeModal');
const modalFilename = document.getElementById('modalFilename');
const modalDocType = document.getElementById('modalDocType');
const modalSummary = document.getElementById('modalSummary');
const modalMissing = document.getElementById('modalMissing');
const modalRisks = document.getElementById('modalRisks');
const modalContent = document.getElementById('modalContent');

uploadForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = fileInput.files[0];
  if (!f) return alert("Please pick a file.");

  submitBtn.disabled = true;
  submitBtn.textContent = "Analyzing...";

  contentBox.innerHTML = "<p class='text-gray-400 text-center'>Extracting text...</p>";
  analysisBox.innerHTML = "<p class='text-gray-400 text-center'>Analyzing content...</p>";

  const fd = new FormData();
  fd.append('document', f);

  try {
    const res = await fetch('/upload', { method: 'POST', body: fd });
    const data = await res.json();

    if (!res.ok) {
      contentBox.innerHTML = `<p class='text-red-500'>${data.error || 'Upload failed'}</p>`;
      analysisBox.innerHTML = `<p class='text-red-500'>Analysis failed</p>`;
    } else {
      contentBox.textContent = data.content || "No text extracted.";
      const a = data.analysis || {};
      modalFilename.textContent = data.filename || "";
      analysisBox.innerHTML = `<p class="font-semibold">${a.analysis_summary || ''}</p>
        <p class="mt-2"><strong>Document type:</strong> ${a.document_type || 'Unknown'}</p>`;
      if (a.missing_items && a.missing_items.length) {
        let html = "<ul class='list-disc pl-5 mt-2'>";
        a.missing_items.forEach(it => html += `<li><strong>${it.item}</strong>: ${it.reason}</li>`);
        html += "</ul>";
        analysisBox.innerHTML += html;
      }
      if (a.risks && a.risks.length) {
        let html = "<p class='mt-3 font-semibold'>Risks:</p><ul class='list-disc pl-5 mt-1'>";
        a.risks.forEach(r => html += `<li>${r}</li>`);
        html += "</ul>";
        analysisBox.innerHTML += html;
      }
    }
  } catch (err) {
    contentBox.innerHTML = `<p class='text-red-500'>Unexpected error</p>`;
    analysisBox.innerHTML = `<p class='text-red-500'>Analysis failed</p>`;
    console.error(err);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Extract & Analyze";
  }
});

historyBtn.addEventListener('click', async () => {
  try {
    const res = await fetch('/history');
    const data = await res.json();
    historyList.innerHTML = '';
    if (data.error) {
      historyList.innerHTML = `<p class='text-red-500'>${data.error}</p>`;
    } else if (data.length === 0) {
      historyList.innerHTML = "<p>No uploads yet.</p>";
    } else {
      data.forEach(d => {
        const el = document.createElement('div');
        el.className = "p-2 border rounded flex justify-between items-center";
        el.innerHTML = `
          <div>
            <div class="font-medium">${d.filename}</div>
            <div class="text-xs text-gray-500">${d.document_type || 'Unknown'} • ${d.created_at}</div>
            <div class="text-sm text-gray-700 mt-1">${d.analysis_summary || ''}</div>
          </div>
          <div class="ml-4">
            <button class="viewBtn px-3 py-1 bg-blue-600 text-white rounded" data-id="${d.id}">View</button>
          </div>
        `;
        historyList.appendChild(el);
      });
      // attach handlers
      document.querySelectorAll('.viewBtn').forEach(btn => {
        btn.addEventListener('click', async (ev) => {
          const id = ev.currentTarget.getAttribute('data-id');
          const r = await fetch(`/document/${id}`);
          const j = await r.json();
          if (r.ok) showModal(j);
          else alert(j.error || 'Failed to fetch document');
        });
      });
    }
    historyPanel.classList.remove('hidden');
  } catch (err) {
    historyList.innerHTML = `<p class='text-red-500'>Failed to fetch history</p>`;
    console.error(err);
  }
});

function showModal(data) {
  modalFilename.textContent = data.filename || '';
  modalDocType.textContent = data.document_type || 'Unknown';
  modalSummary.textContent = data.analysis_summary || '';
  modalMissing.innerHTML = '';
  (data.missing_items || []).forEach(it => {
    const li = document.createElement('li');
    li.textContent = `${it.item}: ${it.reason}`;
    modalMissing.appendChild(li);
  });
  modalRisks.innerHTML = '';
  (data.risks || []).forEach(r => {
    const li = document.createElement('li');
    li.textContent = r;
    modalRisks.appendChild(li);
  });
  modalContent.textContent = data.content || '';
  modal.classList.remove('hidden');
  modal.style.display = 'flex';
}

closeModal.addEventListener('click', () => {
  modal.classList.add('hidden');
  modal.style.display = 'none';
});
</script>
</center>
</body>
</html>
"""

# -----------------------
# Utility: Extract text from file bytes
# -----------------------
def extract_text_from_bytes(filename: str, file_bytes: bytes) -> str:
    text_content = ""
    lower = filename.lower()
    bio = io.BytesIO(file_bytes)
    try:
        if lower.endswith(".docx"):
            doc = docx.Document(bio)
            text_content = "\n".join([p.text for p in doc.paragraphs])
        elif lower.endswith(".pdf"):
            # pdfplumber accepts a file-like object
            with pdfplumber.open(bio) as pdf:
                pages = []
                for page in pdf.pages:
                    txt = page.extract_text()
                    if txt:
                        pages.append(txt)
                text_content = "\n".join(pages)
        else:
            text_content = ""
    except Exception as e:
        print("Extraction error:", e)
        text_content = ""
    return text_content

# -----------------------
# Routes
# -----------------------
@app.route('/')
def home():
    return render_template_string(HTML_CONTENT)

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'document' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files['document']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    try:
        file_bytes = file.read()
        text_content = extract_text_from_bytes(file.filename, file_bytes)
    except Exception as e:
        return jsonify({"error": f"Failed to read file: {str(e)}"}), 500

    # default analysis if no text
    document_analysis = {"document_type": "Unknown", "analysis_summary": "No analysis performed.", "missing_items": [], "risks": []}

    if text_content:
        # Prepare prompt & payload for Gemini
        system_instruction = """You are a legal-tech assistant.
Step 1: Identify the type of document (contract, NDA, employment letter, lease, terms of service, etc.).
Step 2: List potentially missing clauses or essential legal elements.
Step 3: Highlight risks or red flags if present.
Step 4: Return only valid JSON that matches the described schema.
"""

        user_prompt = f"Analyze this document for document type, missing clauses and risks. Return JSON with keys: document_type, analysis_summary, missing_items (array of {{item, reason}}), risks (array of strings).\n\nDocument:\n\n{text_content}"

        payload = {
            "contents": [{"parts": [{"text": user_prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "document_type": {"type": "STRING"},
                        "analysis_summary": {"type": "STRING"},
                        "missing_items": {
                            "type": "ARRAY",
                            "items": {
                                "type": "OBJECT",
                                "properties": {
                                    "item": {"type": "STRING"},
                                    "reason": {"type": "STRING"}
                                }
                            }
                        },
                        "risks": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"}
                        }
                    }
                }
            }
        }

        # If API_KEY is missing, skip LLM call and provide a helpful message
        if not API_KEY:
            document_analysis = {
                "document_type": "Unknown",
                "analysis_summary": "Skipping AI analysis because GOOGLE_API_KEY is not set in environment.",
                "missing_items": [],
                "risks": []
            }
        else:
            try:
                resp = requests.post(API_URL, headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=30)
                resp.raise_for_status()
                resp_json = resp.json()

                # Attempt to extract JSON content robustly
                document_analysis = None
                if resp_json and 'candidates' in resp_json and len(resp_json['candidates'])>0:
                    # The model output is often in candidates[0].content.parts[0].text
                    candidate = resp_json['candidates'][0]
                    content = candidate.get('content', {})
                    parts = content.get('parts', []) if isinstance(content, dict) else []
                    if parts and isinstance(parts, list) and len(parts)>0:
                        text_out = parts[0].get('text', '')
                        # find JSON object inside text_out
                        match = re.search(r'\{.*\}', text_out, re.DOTALL)
                        if match:
                            try:
                                document_analysis = json.loads(match.group(0))
                            except Exception:
                                # fallback: try to evaluate safely by trimming trailing/leading characters
                                # but avoid eval — keep fallback as string message
                                document_analysis = {"document_type": "Unknown", "analysis_summary": "Analysis failed: Could not parse JSON cleanly from model output.", "missing_items": [], "risks": []}
                        else:
                            # maybe it's already the direct JSON (unlikely) or plain text
                            try:
                                document_analysis = json.loads(text_out)
                            except Exception:
                                document_analysis = {"document_type": "Unknown", "analysis_summary": "Analysis failed: Model returned non-JSON output.", "missing_items": [], "risks": []}
                    else:
                        document_analysis = {"document_type": "Unknown", "analysis_summary": "Analysis failed: No content in model response.", "missing_items": [], "risks": []}
                else:
                    document_analysis = {"document_type": "Unknown", "analysis_summary": "Analysis failed: Unexpected response format from LLM.", "missing_items": [], "risks": []}

            except requests.exceptions.RequestException as e:
                document_analysis = {"document_type": "Unknown", "analysis_summary": f"Analysis failed: API error: {str(e)}", "missing_items": [], "risks": []}

    # Save to DB (attempt, but do not fail the API response if DB error occurs)
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        sql = """INSERT INTO documents (filename, document_type, analysis_summary, missing_items, risks, content)
                 VALUES (%s, %s, %s, %s, %s, %s)"""
        vals = (
            file.filename,
            document_analysis.get("document_type", "Unknown"),
            document_analysis.get("analysis_summary", ""),
            json.dumps(document_analysis.get("missing_items", [])),
            json.dumps(document_analysis.get("risks", [])),
            text_content
        )
        cur.execute(sql, vals)
        conn.commit()
        doc_id = cur.lastrowid
        cur.close()
        conn.close()
    except Exception as e:
        print("DB save error:", e)
        doc_id = None

    return jsonify({
        "id": doc_id,
        "filename": file.filename,
        "content": text_content if text_content else "No text could be extracted.",
        "analysis": document_analysis
    })


@app.route('/history', methods=['GET'])
def history():
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id, filename, document_type, analysis_summary, created_at
            FROM documents
            ORDER BY created_at DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        # format datetime
        for r in rows:
            if isinstance(r.get('created_at'), datetime):
                r['created_at'] = r['created_at'].strftime("%Y-%m-%d %H:%M:%S")
        return jsonify(rows)
    except Exception as e:
        return jsonify({"error": f"Database fetch failed: {str(e)}"}), 500

@app.route('/document/<int:doc_id>', methods=['GET'])
def get_document(doc_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM documents WHERE id = %s", (doc_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return jsonify({"error": "Document not found"}), 404

        # convert JSON fields from string to objects if necessary
        try:
            if isinstance(row.get('missing_items'), str):
                row['missing_items'] = json.loads(row['missing_items'])
        except Exception:
            row['missing_items'] = []
        try:
            if isinstance(row.get('risks'), str):
                row['risks'] = json.loads(row['risks'])
        except Exception:
            row['risks'] = []

        # ensure created_at is string
        if isinstance(row.get('created_at'), datetime):
            row['created_at'] = row['created_at'].strftime("%Y-%m-%d %H:%M:%S")
        return jsonify(row)
    except Exception as e:
        return jsonify({"error": f"Database fetch failed: {str(e)}"}), 500

# -----------------------
# Run
# -----------------------
if __name__ == '__main__':
    # helpful debug message
    if not API_KEY:
        print("⚠️ GOOGLE_API_KEY is not set. The app will skip AI analysis and save documents with a placeholder analysis.")
    print(f"Starting app — DB: {DB_USER}@{DB_HOST}/{DB_NAME}")
    app.run(debug=True, port=5000)
