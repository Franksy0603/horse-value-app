import streamlit as st
import pandas as pd
from streamlit_gsheets import GSheetsConnection

st.title("🧪 Google Sheets Connection Tester")

# 1. Check if Secrets are loaded
if "connections" in st.secrets:
    st.success("✅ [connections.gsheets] found in Secrets")
else:
    st.error("❌ [connections.gsheets] is MISSING from Secrets. Check your formatting.")

# 2. Try to connect
try:
    conn = st.connection("gsheets", type=GSheetsConnection)
    st.success("✅ Connection Object Created")
    
    # 3. Try to read the sheet
    url = st.secrets.get("gsheet_url", "")
    df = conn.read(spreadsheet=url, ttl=0)
    st.write("### Data Found in Sheet:")
    st.dataframe(df.head())
    st.success("✅ Successfully READ from Sheet")
    
    # 4. Try a test write
    if st.button("Attempt Test Write"):
        test_df = pd.DataFrame([{"Date": "TEST", "Horse": "CONNECTION TEST"}])
        updated_df = pd.concat([df, test_df], ignore_index=True)
        conn.update(spreadsheet=url, data=updated_df)
        st.balloons()
        st.success("🔥 SUCCESS! Your app has permission to WRITE to the sheet.")
        
except Exception as e:
    st.error(f"⚠️ Error during test: {e}")
    st.info("If you see 'Permission Denied', ensure the client_email from your JSON is an 'Editor' on your Google Sheet.")
