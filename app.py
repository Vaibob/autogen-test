import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from base64 import b64encode
import torch

torch.classes.__path__ = []

# Global API URL
# API_URL = "http://ec2-3-237-51-141.compute-1.amazonaws.com:8000/run-sql"

# Set page configuration
st.set_page_config(
    page_title="LumenAI Reconciler", 
    page_icon="https://s3.amazonaws.com/lumenai.eucloid.com/assets/images/icons/logo.svg", 
    layout="wide", 
    initial_sidebar_state="auto"
)

def add_logo_btn1():
    logo_url = "https://s3.amazonaws.com/lumenai.eucloid.com/assets/images/logo.svg"
    back_button_url = "https://product.lumenai.eucloid.com/home"
    st.sidebar.markdown(
        f"""
        <div style="display: flex; justify-content: flex-start; align-items: center; padding-bottom: 20px;">
            <a href="{back_button_url}" target="_self">
                <img src="https://s3.amazonaws.com/lumenai.eucloid.com/assets/images/icons/back-btn.svg" alt="<-" width="20" height="20" style="margin-right: 10px;">
            </a>
            <div style="text-align: center;">
                <a href="https://product.lumenai.eucloid.com/login" target="_self">
                    <img src="{logo_url}" alt="Logo" width="225" height="fit-content">
                </a>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

def main():
    add_logo_btn1()

    # Add an email input field in the sidebar for the export functionality
    email_id = st.sidebar.text_input("Enter your email for export", placeholder="example@example.com")

    # setup_directories()

    st.sidebar.markdown("<hr>", unsafe_allow_html=True)
    st.sidebar.markdown("<h3 style='margin-bottom: 10px;'>Instructions</h3>", unsafe_allow_html=True)
    st.sidebar.markdown(
        """
        <div style="padding-left: 10px; line-height: 1.6;">
            <strong>1.</strong> Upload exactly 2 files using the uploader below.<br><br>
            <strong>2.</strong> Once the files are valid and you press 'Generate Report'<br><br>
            <strong>3.</strong> The app will first update the database and fetch transaction records and generate a reconciliation report based on one on one comparision of the transactions.<br><br>
        """, 
        unsafe_allow_html=True
    )

    uploaded_files = st.sidebar.file_uploader(
        "Choose exactly 2 files", 
        # type=['pdf', 'xlsx', 'xls', 'csv', 'txt', 'docx', 'png', 'jpg'], 
        accept_multiple_files=True
    )

    # Variables to store file bytes and names
    ledger_one_data = None
    ledger_two_data = None
    ledger_one_file_name = ""
    ledger_two_file_name = ""

    # Validate that exactly 2 files have been uploaded
    if uploaded_files:
        if len(uploaded_files) != 2:
            st.error("Please upload exactly 2 files.")
            return

        col1, col2 = st.columns(2)
        file1, file2 = uploaded_files[0], uploaded_files[1]

        with col1:
            st.subheader(file1.name)
            if file1.name.lower().endswith('.pdf'):
                file_bytes = file1.read()
                base64_pdf = b64encode(file_bytes).decode('utf-8')
                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600"></iframe>'
                st.markdown(pdf_display, unsafe_allow_html=True)
            elif file1.name.lower().endswith(('png', 'jpg', 'jpeg')):
                st.image(file1, use_container_width=True)
            elif file1.name.lower().endswith(('xlsx', 'xls')):
                file1.seek(0)
                try:
                    df = pd.read_excel(file1)
                    st.dataframe(df)
                except Exception as e:
                    st.error(f"Error reading Excel file: {e}")
            elif file1.name.lower().endswith(('csv', 'txt')):
                file1.seek(0)
                content = file1.read().decode('utf-8')
                st.text(content)
            else:
                st.write("Preview not available for this file type.")

        with col2:
            st.subheader(file2.name)
            if file2.name.lower().endswith('.pdf'):
                file_bytes = file2.read()
                base64_pdf = b64encode(file_bytes).decode('utf-8')
                pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="600"></iframe>'
                st.markdown(pdf_display, unsafe_allow_html=True)
            elif file2.name.lower().endswith(('png', 'jpg', 'jpeg')):
                st.image(file2, use_container_width=True)
            elif file2.name.lower().endswith(('xlsx', 'xls')):
                file2.seek(0)
                try:
                    df = pd.read_excel(file2)
                    st.dataframe(df)
                except Exception as e:
                    st.error(f"Error reading Excel file: {e}")
            elif file2.name.lower().endswith(('csv', 'txt')):
                file2.seek(0)
                content = file2.read().decode('utf-8')
                st.text(content)
            else:
                st.write("Preview not available for this file type.")

if __name__ == "__main__":
    main()