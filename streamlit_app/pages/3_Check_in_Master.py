import streamlit as st
import pandas as pd
import requests
import tempfile
import os

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="Check in Master", layout="wide")
st.title("✅ Check Questions in Master Sheet (Unit-wise)")

st.markdown("""
This will:
- Compare each CSV question with the correct **unit sheet** (found from Master sheet)
- Auto write:
  - **0–49%** → add to marks tab (**2/4/8/16**)
  - **50–94%** → add to **Reframed Questions**
  - **95–100%** → ignore
""")

uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

if st.button("Run Check in Master", type="primary"):
    if not uploaded_file:
        st.error("Upload a CSV file first.")
        st.stop()

    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp:
        tmp.write(uploaded_file.getvalue())
        file_path = tmp.name

    try:
        with st.spinner("Working… updating unit sheets…"):
            with open(file_path, "rb") as f:
                resp = requests.post(
                    f"{API_BASE}/check/master",
                    files={"file": f},
                    timeout=300
                )

        data = resp.json()

        if resp.status_code != 200:
            st.error(f"Backend error: {resp.status_code}")
            st.json(data)
            st.stop()

        if "error" in data:
            st.error(data["error"])
            st.json(data)
            st.stop()

        st.success("✅ Completed!")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Extracted", data.get("total_extracted_questions", 0))
        c2.metric("New written", data.get("added_new", 0))
        c3.metric("Reframed written", data.get("added_reframed", 0))
        c4.metric("Duplicates skipped", data.get("skipped_duplicates", 0))

        st.subheader("Details")
        st.dataframe(pd.DataFrame(data.get("details", [])), use_container_width=True)

        st.subheader("Full response")
        st.json(data)

    except Exception as e:
        st.error(f"Backend did not return JSON / error: {e}")
    finally:
        try:
            os.remove(file_path)
        except Exception:
            pass
