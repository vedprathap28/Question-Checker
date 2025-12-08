import streamlit as st

st.set_page_config(page_title="Question Checker", layout="wide")

st.title("📘 Assessment Question Checker")

st.write("Use the left sidebar to navigate.")

st.markdown("""
### Features
- 📥 Import **Previous Papers** (stores questions in DB)
- 🔍 Check **New Assessment CSV** against DB (works with messy CSVs too)
- 📘 Import **Master CSV**
""")
