import streamlit as st
import pandas as pd
import requests
import tempfile
import os



API_BASE = st.secrets.get("API_BASE_URL", os.getenv("API_BASE_URL", "https://vedprathap28-question-checker-backend.hf.space"))


st.set_page_config(page_title="Import Previous Papers", layout="wide")
st.title("📥 Import Previous Papers")

st.write("Upload a previous assessment CSV. The backend will extract questions even if the CSV is messy.")

st.subheader("⬆️ Upload Previous Paper")
assessment_name = st.text_input("Assessment Name")
uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

if st.button("Import Previous Paper", type="primary"):
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
            resp = requests.post(
                f"{API_BASE}/import/assessment",
                data={"assessment_name": assessment_name.strip()},
                files={"file": f},
                timeout=180
            )

        data = resp.json() if resp.text else {}
        if resp.status_code == 200:
            st.success("✅ Import completed!")
            st.json(data)

            # ✅ refresh list immediately (old behavior)
            st.rerun()
        else:
            st.error(f"❌ API error ({resp.status_code})")
            st.json(data)

    except Exception as e:
        st.error(f"❌ Error while calling API: {e}")
    finally:
        try:
            os.remove(file_path)
        except Exception:
            pass

st.markdown("---")
st.subheader("📚 Previously Imported Papers")

try:
    resp = requests.get(f"{API_BASE}/assessments", timeout=30)
    assessments = resp.json() if resp.status_code == 200 else []
except Exception as e:
    st.error(f"❌ Could not load assessments: {e}")
    assessments = []

if not assessments:
    st.info("No assessments imported yet.")
    st.stop()

df = pd.DataFrame(assessments)
st.dataframe(df[["id", "name"]], use_container_width=True)

st.markdown("### 📄 View Paper Details")
id_map = {f'{a["id"]} - {a["name"]}': a["id"] for a in assessments}
label = st.selectbox("Select an imported paper", options=list(id_map.keys()))
selected_id = id_map[label]

col1, col2 = st.columns([3, 1])

with col1:
    if st.button("🔍 Show Details", use_container_width=True):
        try:
            d_resp = requests.get(f"{API_BASE}/assessments/{selected_id}", timeout=60)
            if d_resp.status_code != 200:
                st.error(f"❌ API error ({d_resp.status_code})")
                st.write(d_resp.text)
            else:
                d = d_resp.json()
                st.subheader(f"✅ {d.get('assessment_name', '')}")
                q_df = pd.DataFrame(d.get("questions", []))
                if not q_df.empty:
                    st.dataframe(q_df, use_container_width=True)
                else:
                    st.info("No questions stored for this assessment.")
        except Exception as e:
            st.error(f"❌ Error fetching details: {e}")

with col2:
    if st.button("🗑️ Delete This Paper", use_container_width=True):
        try:
            del_resp = requests.delete(f"{API_BASE}/assessments/{selected_id}", timeout=60)
            if del_resp.status_code == 200:
                st.success("✅ Deleted successfully.")
                st.rerun()
            else:
                st.error(f"❌ Delete failed ({del_resp.status_code})")
                st.write(del_resp.text)
        except Exception as e:
            st.error(f"❌ Error while deleting: {e}")
