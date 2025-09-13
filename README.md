# Backend-Smart-Document-Scanner
This is the backend API for the Smart Document Scanner - a legal-tech tool that allows users to upload contracts (PDF/DOCX) and extracts their text for further analysis. 
Built with Python + Flask.
1]Features
Upload contracts in PDF or DOCX format
Extracts text using:
python-docx for .docx files
pdfplumber (with fallback to PyPDF2) for .pdf files
Returns extracted text in JSON format
Lightweight and easy to extend for legal clause detection

2]Tech Stack
Flask (Python web framework)
pdfplumber / PyPDF2 (PDF parsing)
python-docx (DOCX parsing)

