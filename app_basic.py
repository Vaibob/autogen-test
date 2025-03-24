import duckdb
import streamlit as st
import os
import time
import asyncio
import pandas as pd
import mysql.connector
from datetime import datetime
import subprocess
import uuid
import logging
import io
import base64
from autogen import reconcile_files 

# Configure logging
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.FileHandler("app.log"),
#         logging.StreamHandler()
#     ]
# )
logger = logging.getLogger(__name__)

BREVO_API_KEY = "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"
SENDER_EMAIL = "vaibhavshelartest@gmail.com"
SENDER_NAME = "Eucloid Data Solutions"

try:
    from sib_api_v3_sdk import ApiClient, Configuration, TransactionalEmailsApi, SendSmtpEmail
    from sib_api_v3_sdk.rest import ApiException
    EMAIL_ENABLED = True
    logger.info("Brevo SDK successfully imported. Email functionality is enabled.")
except ImportError:
    EMAIL_ENABLED = False
    logger.info("Brevo SDK not available. Email functionality is disabled.")


st.set_page_config(
    page_title="File Reconciliation App",
    page_icon="https://s3.amazonaws.com/lumenai.eucloid.com/assets/images/icons/logo.svg",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom styles
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E88E5;
        margin-bottom: 1rem;
    }
    .sub-header {
        font-size: 1.5rem;
        font-weight: 600;
        color: #0D47A1;
    }
    .status-success {
        padding: 0.5rem;
        background-color: #E8F5E9;
        border-left: 5px solid #4CAF50;
        margin-bottom: 1rem;
    }
    .status-info {
        padding: 0.5rem;
        background-color: #E3F2FD;
        border-left: 5px solid #2196F3;
        margin-bottom: 1rem;
    }
    .status-warning {
        padding: 0.5rem;
        background-color: #FFF8E1;
        border-left: 5px solid #FFC107;
        margin-bottom: 1rem;
    }
    .status-error {
        padding: 0.5rem;
        background-color: #FFEBEE;
        border-left: 5px solid #F44336;
        margin-bottom: 1rem;
    }
    /* Make the tabs more visible */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #F0F2F6;
        border-radius: 4px 4px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
    }
    /* Add shadow to dataframes */
    .stDataFrame {
        box-shadow: 0 4px 8px 0 rgba(0, 0, 0, 0.1);
        border-radius: 5px;
    }
    .stDownloadButton {
        margin-top: 1rem;
    }
</style>
""", unsafe_allow_html=True)

# --- Database connection helper ---
def get_db_connection():
    """Establish a connection to the DuckDB database"""
    try:
        connection = duckdb.connect(database='autogen.duckdb')
        return connection
    except Exception as e:
        logger.error(f"DuckDB connection error: {str(e)}")
        st.error(f"DuckDB connection error. Please check your setup.")
        return None

# --- Database query functions ---
def get_matching_transactions(client_id):
    """Retrieve matching transactions for a specific client_id"""
    conn = get_db_connection()
    if conn:
        try:
            query = f"""
            SELECT * FROM matching_transactions
            WHERE client_id = {client_id}
            ORDER BY date_client DESC
            """
            df = conn.execute(query).fetchdf()
            conn.close()
            return df
        except Exception as e:
            logger.error(f"Error fetching matching transactions: {str(e)}")
            st.error(f"Error fetching matching transactions. Please try again.")
            conn.close()
    return pd.DataFrame()


def get_non_matching_transactions(client_id):
    """Retrieve non-matching transactions for a specific client_id"""
    conn = get_db_connection()
    if conn:
        try:
            query = f"""
            SELECT * FROM non_matching_transactions
            WHERE client_id = {client_id}
            ORDER BY date_client DESC, date_vendor DESC
            """
            df = conn.execute(query).fetchdf()
            conn.close()
            return df
        except Exception as e:
            logger.error(f"Error fetching non-matching transactions: {str(e)}")
            st.error(f"Error fetching non-matching transactions. Please try again.")
            conn.close()
    return pd.DataFrame()


def format_currency(val):
    """Format currency values with the ₹ symbol and proper formatting"""
    if pd.isna(val) or val == 0:
        return "-"
    return f"₹{val:,.2f}"


def format_dataframe(df):
    """Apply formatting to the dataframe for display"""
    formatted_df = df.copy()
    
    # Format date columns
    for date_col in ['date_client', 'date_vendor']:
        if date_col in formatted_df.columns:
            formatted_df[date_col] = pd.to_datetime(formatted_df[date_col], errors='coerce')
            formatted_df[date_col] = formatted_df[date_col].dt.strftime('%d-%m-%Y')
            formatted_df[date_col] = formatted_df[date_col].fillna("-")
    
    # Format currency columns
    for col in ['Debit_client', 'Credit_client', 'Debit_vendor', 'Credit_vendor']:
        if col in formatted_df.columns:
            formatted_df[col] = formatted_df[col].apply(format_currency)
    
    return formatted_df


def save_uploaded_files(files, file_type):
    """Save uploaded files to a temporary directory and return their paths"""
    if not files:
        return []
    
    # Create a unique session directory to avoid file conflicts
    session_id = st.session_state.get('session_id', str(uuid.uuid4()))
    st.session_state['session_id'] = session_id
    
    temp_dir = os.path.join("temp_uploads", session_id, file_type)
    os.makedirs(temp_dir, exist_ok=True)
    
    file_paths = []
    with st.spinner(f"Saving {file_type} files..."):
        for file in files:
            file_path = os.path.join(temp_dir, file.name)
            with open(file_path, "wb") as f:
                f.write(file.getbuffer())
            file_paths.append(file_path)
            logger.info(f"Saved {file_type} file: {file.name}")
    
    return file_paths


def cleanup_temp_files(client_paths, vendor_paths):
    """Remove temporary files after processing"""
    for path in client_paths + vendor_paths:
        try:
            if os.path.exists(path):
                os.remove(path)
                logger.info(f"Removed temporary file: {path}")
        except Exception as e:
            logger.error(f"Error removing file {path}: {str(e)}")


def display_progress_bar(process_name):
    """Display a progress indicator for the reconciliation process"""
    # Create a container for the progress elements
    progress_container = st.empty()
    
    # Initial status - In Progress
    progress_container.markdown(
        """
        <div style="margin: 20px 0;">
            <div style="display: flex; align-items: center; margin-bottom: 10px;">
                <div class="stSpinner">
                    <div class="st-ae st-af st-ag st-ah st-ai st-aj"></div>
                </div>
                <span style="margin-left: 10px; font-size: 16px;">Reconciliation in progress...</span>
            </div>
            <div style="height: 6px; background-color: #e6f3ff; border-radius: 3px;">
                <div style="width: 100%; height: 100%; background-color: #2185d0; border-radius: 3px; animation: progress-bar-animation 2s linear infinite;"></div>
            </div>
        </div>
        <style>
            @keyframes progress-bar-animation {
                0% { background-position: 0 0; }
                100% { background-position: 100px 0; }
            }
        </style>
        """,
        unsafe_allow_html=True
    )
    
    return progress_container


# --- UI Components ---
def render_header():
    """Render the application header"""
    st.markdown("<div class='main-header'>LumenAI Reconciler</div>", unsafe_allow_html=True)
    st.markdown(
        """
        This application helps you reconcile client and vendor files by:
        1. Analyzing and extracting transaction data
        2. Matching transactions between client and vendor records
        3. Identifying discrepancies and generating reports
        
        Upload your files below to get started.
        """
    )
    st.divider()


def add_logo():
    """Add the company logo to the sidebar"""
    logo_url = "https://s3.amazonaws.com/lumenai.eucloid.com/assets/images/logo.svg"
    st.sidebar.markdown(
        f"""
        <div style="display: flex; justify-content: center; align-items: center; padding-bottom: 20px;">
            <a href="#" target="_self">
                <img src="{logo_url}" alt="Logo" width="225" height="fit-content">
            </a>
        </div>
        """,
        unsafe_allow_html=True
    )

def render_sidebar():
    """Render the application sidebar with controls and information"""
    with st.sidebar:
        # Add logo at the top
        add_logo()
        
        st.header("Email for Results")
        email = st.sidebar.text_input("Enter email to receive results", placeholder="your.email@example.com", 
                             help="Results will be automatically sent to this email when reconciliation completes")

        if email:
            st.session_state['export_email'] = email
        
        st.divider()
        
        # Utility buttons
        if st.button("Clear Cache", use_container_width=True):
            try:
                result = subprocess.run(
                    ["streamlit", "cache", "clear"],
                    capture_output=True, text=True, check=True
                )
                st.success("Cache cleared!")
                logger.info("Cache cleared successfully")
            except Exception as e:
                logger.error(f"Failed to clear cache: {str(e)}")
                st.error(f"Failed to clear cache: {str(e)}")
        
        if st.button("New Session", use_container_width=True):
            # Reset all session state variables
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            logger.info("Started new session")
            st.success("New session started!")
            st.rerun()
        
        st.divider()
        
        # Help accordion
        with st.expander("Help & Documentation"):
            st.markdown("""
            ### How to use this app
            
            1. **Upload Files**: Use the file uploaders to select client and vendor files
            2. **Start Reconciliation**: Click the button to begin processing
            3. **View Results**: Check the matching and non-matching transactions tabs
            4. **Download Results**: Use the download buttons to export the data
            
            ### Supported File Types
            
            - PDF documents (.pdf)
            - Excel spreadsheets (.xlsx)
            - CSV files (.csv)
            - Images (.jpg, .png)
            
            ### Need Help?
            
            Contact support at https://www.eucloid.com/#Talk
            """)


def render_file_upload_section():
    """Render the file upload section"""

    # 1. Initialize expander state in session_state if it doesn't exist
    if 'upload_files_expanded' not in st.session_state:
        st.session_state['upload_files_expanded'] = True  # Start expanded

    with st.expander("Upload Files", expanded=st.session_state['upload_files_expanded']):
        st.markdown("<div class='sub-header'>Upload Your Files</div>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("### Client Files")
            client_files = st.file_uploader(
                "Upload client statements, invoices, or ledgers",
                accept_multiple_files=True,
                type=["pdf", "xlsx", "csv", "jpg", "png"]
            )

        with col2:
            st.markdown("### Vendor Files")
            vendor_files = st.file_uploader(
                "Upload vendor statements, invoices, or ledgers",
                accept_multiple_files=True,
                type=["pdf", "xlsx", "csv", "jpg", "png"]
            )

        st.markdown("### File Guidelines")
        st.info("""
        - For best results, ensure all files are clearly readable
        - Statements should include transaction dates, amounts, and references
        - PDF files should not be password-protected
        """)

        if st.button("Start Reconciliation", use_container_width=True, type="primary"):
            if not client_files and not vendor_files:
                st.warning("Please upload at least one file for reconciliation.")
            else:
                # Save uploaded files and get their paths
                client_file_paths = save_uploaded_files(client_files, "client")
                vendor_file_paths = save_uploaded_files(vendor_files, "vendor")

                # Set session state for processing
                st.session_state['processing'] = True
                st.session_state['client_file_paths'] = client_file_paths
                st.session_state['vendor_file_paths'] = vendor_file_paths

                # 2.  IMPORTANT:  Keep the expander open!
                st.session_state['upload_files_expanded'] = True

                # Rerun to start processing
                st.rerun()

    # 3. Update expander state whenever the expander is clicked
    st.session_state['upload_files_expanded'] = st.session_state['upload_files_expanded']

def process_files(client_file_paths, vendor_file_paths):
    """Process the uploaded files through the reconciliation workflow"""
    try:
        # Display progress indicator
        progress_container = display_progress_bar("Reconciliation")
        
        # Run the reconciliation function using asyncio
        client_id = asyncio.run(
            reconcile_files(client_file_paths, vendor_file_paths)
        )
        
        # Update session state
        st.session_state['client_id'] = client_id
        st.session_state['reconciliation_complete'] = True
        st.session_state['processing'] = False
        
        # Show completion message
        progress_container.markdown(
            """
            <div style="margin: 20px 0;">
                <div style="display: flex; align-items: center; margin-bottom: 10px;">
                    <span style="margin-left: 0px; font-size: 16px;">Reconciliation - Completed!</span>
                </div>
                <div style="height: 6px; background-color: #e6f3ff; border-radius: 3px;">
                    <div style="width: 100%; height: 100%; background-color: #21ba45; border-radius: 3px;"></div>
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )
        
        logger.info(f"Reconciliation completed successfully for client ID: {client_id}")
        
        # Send email if an address was provided
        if 'export_email' in st.session_state and st.session_state['export_email']:
            email = st.session_state['export_email']
            logger.info(f"Attempting to send email to: {email}")
            
            with st.spinner("Sending reconciliation report to your email..."):
                try:
                    if EMAIL_ENABLED:
                        # Get the reconciliation data
                        matching_df = get_matching_transactions(client_id)
                        non_matching_df = get_non_matching_transactions(client_id)
                        
                        # Always attempt to send even if one DataFrame is empty
                        success = export_final_excel(matching_df, non_matching_df, email)
                        
                        if success:
                            st.success(f"Report sent to {email}")
                            logger.info(f"Report exported and sent to {email}")
                        else:
                            st.error("Failed to send email. Check logs for details.")
                            logger.error("Email sending failed")
                    else:
                        st.info("Email functionality is not available. Please check if the Brevo SDK is installed.")
                        logger.warning("Email functionality is disabled")
                except Exception as e:
                    st.error(f"Failed to send report: {str(e)}")
                    logger.error(f"Email export error: {str(e)}")
                    import traceback
                    logger.error(traceback.format_exc())
                
        # Clean up temporary files
        cleanup_temp_files(client_file_paths, vendor_file_paths)
        
        return client_id
            
    except Exception as e:
        st.session_state['error_occurred'] = True
        st.session_state['error_message'] = str(e)
        st.session_state['processing'] = False
        
        logger.error(f"Error during reconciliation: {str(e)}")
        
        # Clean up temporary files
        cleanup_temp_files(client_file_paths, vendor_file_paths)
        
        # Show detailed error
        st.error("An error occurred during reconciliation")
        with st.expander("Error Details"):
            st.exception(e)
        
        return None


def render_results(client_id):
    """Render the reconciliation results in tabs"""
    st.markdown(f"<div class='sub-header'>Reconciliation Results</div>", unsafe_allow_html=True)
    
    # Create tabs for different result views
    tab1, tab2, tab3 = st.tabs(["Matching Transactions", "Non-Matching Transactions", "Summary"])
    
    with tab1:
        st.subheader("Matching Transactions")
        matching_df = get_matching_transactions(client_id)
        
        if not matching_df.empty:
            # Display metrics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Matches", len(matching_df))
            with col2:
                total_debit = matching_df["Debit_client"].sum()+matching_df["Debit_vendor"].sum()
                st.metric("Total Debit", f"₹{total_debit:,.2f}")
            with col3:
                total_credit = matching_df["Credit_client"].sum()+matching_df["Credit_vendor"].sum()
                st.metric("Total Credit", f"₹{total_credit:,.2f}")
            
            # Format and display the dataframe
            formatted_df = format_dataframe(matching_df)
            st.dataframe(formatted_df, use_container_width=True)
            
            # Download button
            csv = matching_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "Download Matching Transactions CSV",
                csv,
                f"matching_transactions_{client_id}_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv",
                key="download_matching"
            )
        else:
            st.info("No matching transactions found.")
    
    with tab2:
        st.subheader("Non-Matching Transactions")
        non_matching_df = get_non_matching_transactions(client_id)
        
        if not non_matching_df.empty:
            # Display metrics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Discrepancies", len(non_matching_df))
            with col2:
                total_client = non_matching_df["Debit_client"].sum() + non_matching_df["Credit_client"].sum()
                st.metric("Client Amount", f"₹{total_client:,.2f}")
            with col3:
                total_vendor = non_matching_df["Debit_vendor"].sum() + non_matching_df["Credit_vendor"].sum()
                st.metric("Vendor Amount", f"₹{total_vendor:,.2f}")
            
            # Format and display the dataframe
            formatted_df = format_dataframe(non_matching_df)
            st.dataframe(formatted_df, use_container_width=True)
            
            # Download button
            csv = non_matching_df.to_csv(index=False).encode('utf-8')
            st.download_button(
                "Download Non-Matching Transactions CSV",
                csv,
                f"non_matching_transactions_{client_id}_{datetime.now().strftime('%Y%m%d')}.csv",
                "text/csv",
                key="download_non_matching"
            )
        else:
            st.info("No non-matching transactions found.")
    
    with tab3:
        st.subheader("Reconciliation Summary")
        
        # Get both dataframes
        matching_df = get_matching_transactions(client_id)
        non_matching_df = get_non_matching_transactions(client_id)
        
        # Calculate summary statistics
        total_matches = len(matching_df)
        total_discrepancies = len(non_matching_df)
        total_transactions = total_matches + total_discrepancies
        
        match_percentage = 0
        if total_transactions > 0:
            match_percentage = (total_matches / total_transactions) * 100
        
        # Display summary metrics
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Transactions", total_transactions)
        with col2:
            st.metric("Match Rate", f"{match_percentage:.1f}%")
        with col3:
            st.metric("Discrepancy Rate", f"{100 - match_percentage:.1f}%")
        
        # Create summary chart
        if total_transactions > 0:
            st.bar_chart({
                "Matching": [total_matches],
                "Non-Matching": [total_discrepancies]
            })
        
        # Show timestamp
        st.info(f"Reconciliation completed on {datetime.now().strftime('%B %d, %Y at %H:%M:%S')}")


def render_error_page():
    """Render the error page when reconciliation fails"""
    st.markdown("<div class='status-error'>❌ Reconciliation Failed</div>", unsafe_allow_html=True)
    
    st.error(st.session_state.get('error_message', 'An unknown error occurred during reconciliation.'))
    
    with st.expander("Troubleshooting Steps"):
        st.markdown("""
        ### Please try the following:
        
        1. Check that your files are in the correct format and not corrupted
        2. Ensure your database connection is working properly
        3. Verify that the AutoGen module is correctly installed
        4. Try with a smaller set of files first
        5. Check the application logs for detailed error information
        
        If the problem persists, please contact technical support.
        """)
    
    if st.button("Reset and Try Again", use_container_width=True):
        # Reset error state but keep the session ID
        session_id = st.session_state.get('session_id')
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        if session_id:
            st.session_state['session_id'] = session_id
        st.rerun()


def initialize_brevo_client():
    """Initialize Brevo API client configuration"""
    if not EMAIL_ENABLED:
        logger.warning("Email functionality is disabled")
        return None
    
    try:    
        configuration = Configuration()
        configuration.api_key['api-key'] = BREVO_API_KEY
        api_client = ApiClient(configuration)
        logger.info("Brevo client initialized successfully")
        return api_client
    except Exception as e:
        logger.error(f"Error initializing Brevo client: {str(e)}")
        return None

def export_final_excel(matched_df, non_reconciled_df, email_id):
    """
    Generates an Excel file with two sheets and sends via Brevo API.
    Args:
        matched_df (pd.DataFrame): DataFrame containing matched transactions.
        non_reconciled_df (pd.DataFrame): DataFrame containing non-reconciled transactions.
        email_id (str): Recipient email address.
    Returns:
        bool: True if the email was sent successfully.
    """
    if not EMAIL_ENABLED:
        logger.warning("Email functionality is disabled")
        return False
    
    if not email_id:
        logger.warning("No email address provided")
        return False
        
    try:
        # Log start of process
        logger.info(f"Starting export to email: {email_id}")
        
        # Step 1: Generate the Excel file in memory and encode it
        logger.info("Creating Excel file in memory")
        output = io.BytesIO()
        
        try:
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                # Handle empty DataFrames
                if matched_df is None or matched_df.empty:
                    pd.DataFrame().to_excel(writer, sheet_name='Matched', index=False)
                else:
                    matched_df.to_excel(writer, sheet_name='Matched', index=False)
                
                if non_reconciled_df is None or non_reconciled_df.empty:
                    pd.DataFrame().to_excel(writer, sheet_name='Non Reconciled', index=False)
                else:
                    non_reconciled_df.to_excel(writer, sheet_name='Non Reconciled', index=False)
        except Exception as e:
            logger.error(f"Error creating Excel file: {str(e)}")
            raise  # Re-raise to be caught by the outer try/except
            
        output.seek(0)  # Important: reset position to the start
        excel_data = output.getvalue()
        excel_base64 = base64.b64encode(excel_data).decode('utf-8')
        logger.info(f"Excel file created and encoded, size: {len(excel_data)} bytes")
        
        # Step 2: Prepare the email content and attachment
        subject = "Your LumenAI Reconciliation Report"
        html_content = """
        <html>
            <body>
                <p>Hello,</p>
                <p>Please find attached the reconciliation report with Matched and Non Reconciled data.</p>
                <p>This report contains:</p>
                <ul>
                    <li>Matched Transactions</li>
                    <li>Non-Matched Transactions</li>
                </ul>
                <p>Thank you for using LumenAI Reconciler.</p>
            </body>
        </html>
        """
        attachment = {
            "name": "reconciliation_report.xlsx",
            "content": excel_base64
        }
        
        # Step 3: Initialize the Brevo API client
        logger.info("Initializing Brevo API client")
        api_client = initialize_brevo_client()
        
        if api_client is None:
            logger.error("Failed to initialize Brevo API client")
            return False
            
        api_instance = TransactionalEmailsApi(api_client)
        
        # Step 4: Create the email object and send the email
        logger.info(f"Creating and sending email to {email_id}")
        send_smtp_email = SendSmtpEmail(
            to=[{"email": email_id}],
            sender={"email": SENDER_EMAIL, "name": SENDER_NAME},
            subject=subject,
            html_content=html_content,
            attachment=[attachment]
        )
        
        try:
            api_response = api_instance.send_transac_email(send_smtp_email)
            logger.info(f"Email sent successfully: {api_response}")
            return True
        except ApiException as e:
            logger.error(f"Brevo API exception: {e.reason if hasattr(e, 'reason') else str(e)}")
            if hasattr(e, 'body'):
                logger.error(f"API response body: {e.body}")
            return False
        
    except Exception as e:
        logger.error(f"Unexpected error in export_final_excel: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False

# --- Main Application ---
def main():
    """Main application function"""
    # Initialize session state
    if 'client_id' not in st.session_state:
        st.session_state.client_id = None
    if 'reconciliation_complete' not in st.session_state:
        st.session_state.reconciliation_complete = False
    if 'error_occurred' not in st.session_state:
        st.session_state.error_occurred = False
    if 'processing' not in st.session_state:
        st.session_state.processing = False
    
    # Render header and sidebar
    render_header()
    render_sidebar()
    
    # Handle error state
    if st.session_state.get('error_occurred', False):
        render_error_page()
        return
    
    # Handle processing state
    if st.session_state.get('processing', False):
        client_file_paths = st.session_state.get('client_file_paths', [])
        vendor_file_paths = st.session_state.get('vendor_file_paths', [])
        
        client_id = process_files(client_file_paths, vendor_file_paths)
        
        if client_id:
            st.rerun()  # Rerun to refresh UI with results
        return
    
    # Handle results display or file upload
    if st.session_state.get('reconciliation_complete', False) and st.session_state.get('client_id'):
        render_results(st.session_state.client_id)
    else:
        render_file_upload_section()
    
    # Footer
    st.divider()
    col1, col2 = st.columns([3, 1])
    with col1:
        st.caption("LumenAI Reconciler © 2025")
    with col2:
        st.caption("v1.0.0")


if __name__ == "__main__":
    main()