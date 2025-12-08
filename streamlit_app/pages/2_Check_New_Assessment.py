import streamlit as st
import pandas as pd
import requests
import tempfile
import os

API_BASE = st.secrets.get("API_BASE_URL", os.getenv("API_BASE_URL", "http://127.0.0.1:8000"))


st.set_page_config(page_title="Check New Assessment", layout="wide")
st.title("🔍 Check New Assessment Against Previous Papers")

st.write("""
Upload a **new assessment CSV** (even messy CSVs).  
Backend will extract questions automatically and compare against DB.
""")

assessment_name = st.text_input("Assessment Name", placeholder="e.g., Mid Exam - Set A")
uploaded_file = st.file_uploader("Upload New Assessment CSV", type=["csv"])

def tag(score):
    if score >= 95:
        return "🟢 Duplicate"
    if score >= 50:
        return "🟡 Reframed"
    return "🔵 New"

if st.button("Check Similarity", type="primary"):
    if not uploaded_file:
        st.error("⚠️ Please upload a CSV file.")
        st.stop()
    if not assessment_name.strip():
        st.error("⚠️ Please enter an assessment name.")
        st.stop()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(uploaded_file.getvalue())
        file_path = tmp.name

    try:
        with open(file_path, "rb") as f:
            response = requests.post(
                f"{API_BASE}/check/new",
                data={"assessment_name": assessment_name},
                files={"file": f},
                timeout=180
            )

        result = response.json()

        if "error" in result:
            st.error(result["error"])
            st.stop()

        overall = float(result.get("overall_similarity_percentage", 0))
        st.subheader("📊 Overall Similarity")
        st.write(f"**{overall}%**")
        st.progress(min(int(overall), 100))

        st.info(f"📌 Duplicate questions found within this uploaded paper: **{result.get('duplicates_within_uploaded_paper', 0)}**")

        details = result.get("details", [])
        df = pd.DataFrame(details)
        if df.empty:
            st.warning("No questions extracted.")
            st.stop()

        df["Match"] = df["similarity_percentage"].apply(tag)

        # ✅ show your required columns
        cols = [
            "new_question",
            "duplicate",
            "duplicate_question",
            "closest_previous_question",
            "matched_college",
            "similarity_percentage",
            "Match",
            "category",
            "marks",
            "unit",
            "confidence",
        ]
        df = df[[c for c in cols if c in df.columns]]

        st.subheader("🧾 Results")
        st.dataframe(df, use_container_width=True)

        st.caption("Confidence is how strongly the extractor believes that cell is actually a question (0–1).")

    except Exception as e:
        st.error(f"❌ Error occurred: {e}")
    finally:
        try:
            os.remove(file_path)
        except Exception:
            pass
