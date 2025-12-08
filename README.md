# Question-Checker

A tool to:
- Import Previous Papers (CSV) into DB
- Check New Assessment CSV against previous papers
- Check in Master

## Run Backend (FastAPI)
```bash
cd backend
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload





cd streamlit_app
python -m venv .venv
.\.venv\Scripts\activate
pip install -r ../backend/requirements.txt
streamlit run app.py
