from typing import Optional, List, Tuple
from autogen_core.code_executor import ImportFromModule
from autogen_core.tools import FunctionTool
import duckdb
import mysql.connector
import pandas as pd
import logging
import google.generativeai as genai
import json
import re
from datetime import datetime
# genai.configure(api_key="AIzaSyDmt-PWtcH3t4x9W4ehh4822aS0JVpj_Rk")
genai.configure(api_key="AIzaSyCfFrtg0ofIMydEz6hgxbieIzUZ9WCHj0U")
# prompt_instruction = """
# 2. **Data Cleaning:**
#    - **Date Formatting (Posting Date - Special Handling):**
#      - The "Posting Date" column in the Excel file may contain visually inconsistent date formats.
#      - **Interpret and convert the dates in the "Posting Date" column, adhering to these rules *simultaneously*:**
#        - **Separator Rule:**
#          - **If the date uses hyphens (`-`) as separators, initially interpret it as `mm-dd-yyyy`.**
#          - **If the date uses slashes (`/`) as separators, initially interpret it as `dd/mm/yyyy`.**
#        - **Strict Chronological Order:**  The dates *must* be in strict chronological order. Each date must be greater than or equal to the preceding date.
#        - **Adjacent Date Comparison:** Use the information from *both preceding and subsequent* dates to resolve ambiguities and confirm the month assignments. If the separator rule leads to a date that violates chronological order, *override the separator rule* and adjust the month to maintain chronological order.
#        - **Latest Date Limit:** No date can be later than the final date in the column.
#        - Convert the correctly interpreted dates to the "dd-MMM-yy" format (e.g., "12-Oct-23").

#      - **Specific Examples (Illustrating Inference):**
#         - **From the main image (applying all rules):**
#            - "29/04/24"    ->  "29-Apr-24" (Separator rule: dd/mm/yyyy)
#            - "05-06-2024"  ->  "06-May-24" (Separator rule: mm-dd-yyyy)
#            - "05-09-2024"  ->  "09-May-24"  (Separator: mm-dd, Chronological Override: May)
#            - "05-10-2024"  ->  "10-May-24"  (Separator: mm-dd, Chronological Override: May)
#            - "22/05/24"    ->  "22-May-24" (Separator rule: dd/mm/yyyy)
#            - "06-08-2024"  ->  "08-Jun-24"  (Separator: mm-dd, Chronological Override: Jun)
#            - "06-11-2024"  ->  "11-Jun-24"  (Separator: mm-dd, Chronological Override: Jun)
#            - "18/06/24"    ->  "18-Jun-24" (Separator rule: dd/mm/yyyy)
#            - "24/06/24"    ->  "24-Jun-24" (Separator rule: dd/mm/yyyy)
#            - "07-08-2024"  ->  "08-Jul-24" (Separator rule: mm-dd-yyyy)
#            - "18/07/24"    ->  "18-Jul-24" (Separator rule: dd/mm/yyyy)
#            - "23/07/24"    ->  "23-Jul-24" (Separator rule: dd/mm/yyyy)
#            - "29/07/24"    ->  "29-Jul-24" (Separator rule: dd/mm/yyyy)
#            - "29/07/24"    ->  "29-Jul-24" (Separator rule: dd/mm/yyyy)
#         - **Additional Clarifying Examples:**
#            - "03-07-2024"  ->  "07-Mar-24" (Separator: mm-dd, Chronological Override: Mar)
#            - "03-11-2024"  ->  "11-Mar-24" (Separator: mm-dd, Chronological Override: Mar)

#      - **General Principle:**
#        1.  **Separator Rule:**  `-` implies `mm-dd-yyyy`; `/` implies `dd/mm/yyyy`.  Use this as the *initial* interpretation.
#        2.  **Strict Chronological Order:**  This *overrides* the separator rule if necessary.
#        3.  **Latest Date Limit:**  No date can be later than the last.
#        4.  **Adjacent Date Comparison:**  Use both preceding and subsequent dates to confirm and correct.

#    - **Date Formatting (Other Dates):** For other date columns (e.g., "Due Date"), apply the *same rules*: separator-based initial interpretation, strict chronological order (which can override the separator rule), adjacent date comparison, and conversion to "dd-MMM-yy".  Do *not* apply the "latest date" constraint unless explicitly stated for that column.

#    - **Numeric Fields:** Remove non-numeric characters from debit, credit, balance_due, and cumulative_balance.
#    - **Null Handling:** Replace missing values (NaN, empty, or null) with an empty string ("").

# 3. **Output Format:**
#    - Return data as a **JSON array**, where each row follows this structure:

#      ```json
#      [
#        {
#          "transaction_num": "123",
#          "date": "12-Oct-23",
#          "due_date": "15-Oct-23",
#          "particulars": "Payment received",
#          "debit": 10.00,
#          "credit": 0.00,
#          "balance_due": 0.00,
#          "cumulative_balance": 0.00
#        }
#      ]
#      ```
#    - Ensure proper JSON syntax and structure before returning the output.
#    - This data is dummy data to make you understand the format of the JSON; do not use it when inferring.
#    - Make sure the numeric values are not string

# #### **Output Requirement:**
# - The final output should be a **single JSON array** containing all extracted transactions.
# """
prompt_instruction = """1. **Identify Tabular Data:**
   - Locate the table containing transaction details and extract the following columns:
     - **Transaction Number**
     - **Posting Date**
     - **Due Date**
     - **Description**
     - **Debit Amount**
     - **Credit Amount**
     - **Balance Due**
     - **Cumulative Balance**

2. **Data Cleaning:**
   - **Date Formatting (General Rules):**
     - Convert all dates to the "dd-MMM-yy" format (e.g., "05-Apr-24", "04-May-24").
     - **Determine the input date format based on the separator:**
       - If the date uses a hyphen (`-`) as a separator (e.g., "04-05-24"), assume the format is **MM-DD-YY** (Month-Day-Year). Therefore, "04-05-24" should be interpreted as April 5th, 2024, and converted to "05-Apr-24".
       - If the date uses a slash (`/`) as a separator (e.g., "04/05/24"), assume the format is **DD-MM-YY** (Day-Month-Year). Therefore, "04/05/24" should be interpreted as May 4th, 2024, and converted to "04-May-24".
       - If the date uses any other separator, or no separator, and the format is ambiguous, refer to the "Posting Date - Special Handling" rules below.

   - **Date Formatting (Posting Date - Special Handling):**
     - The "Posting Date" column in the Excel file may contain visually inconsistent date formats.
     - **Crucially, assume the dates in the "Posting Date" column are presented in *chronological order*, regardless of their visual appearance or separator.**
     - Use this chronological order to *infer* the correct day, month, and year *if the separator rule above cannot definitively determine the format*.
     - Convert the inferred dates to the "dd-MMM-yy" format.
     - **Specific Example (Based on provided image):** The provided image shows a "Posting Date" column. Even though the dates *look* like "04-03-2024", "04-08-2024", etc., you should interpret them based on the chronological sequence. The correct interpretation and conversion should be:
        - "04-03-2024" -> "03-Apr-24"
        - "04-08-2024" -> "08-Apr-24"
        - "04-10-2024" -> "10-Apr-24"
        - "23/05/24" -> "23-May-24"
        - "23/05/24" -> "23-May-24"
        - "23/05/24" -> "23-May-24"
        - "24/05/24" -> "24-May-24"
        - "15/06/24" -> "15-Jun-24"
        - "19/06/24" -> "19-Jun-24"
        - "26/06/24" -> "26-Jun-24"
        - "07-10-2024" -> "10-Jul-24"
        - "07-12-2024" -> "12-Jul-24"
     - **General Principle:** Always prioritize the chronological order of the dates in the "Posting Date" column to determine the correct month and day if the separator rule is insufficient.

   - **Date Formatting (Other Dates):** For other date columns (e.g., "Due Date"), apply the separator-based format rules first. If the format remains ambiguous, and chronological context is available, use that to infer the correct date. Convert all dates to "dd-MMM-yy".

   - **Numeric Fields:** Remove non-numeric characters from debit, credit, balance_due, and cumulative_balance.
   - **Null Handling:** Replace missing values (NaN, empty, or null) with an empty string ("").

3. **Output Format:**
   - Return data as a **JSON array**, where each row follows this structure:

     ```json
     [
       {
         "transaction_num": "123",
         "date": "12-Oct-23",
         "due_date": "15-Oct-23",
         "particulars": "Payment received",
         "debit": 10.00,
         "credit": 0.00,
         "balance_due": 0.00,
         "cumulative_balance": 0.00
       }
     ]
     ```
   - Ensure proper JSON syntax and structure before returning the output.
   - This data is dummy data to make you understand the format of the JSON; do not use it when inferring.
   - Make sure the numeric values are not string

#### **Output Requirement:**
- The final output should be a **single JSON array** containing all extracted transactions.
"""

def clean_and_parse_chat_response(chat_response):
    chat_response = chat_response.replace("```json", "").strip()
    chat_response = chat_response.replace("```", "").strip()
    chat_response = re.sub(r'[\x00-\x1F]+', '', chat_response)

    # Convert JSON string to dictionary
    return json.loads(chat_response)

def format_date(date_str):
    if not date_str:  # Check for None or empty string
        print("Received an empty or None date value.")
        return None

    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue


DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "12345678",
    "database": "autogen"
}


def extract_data_with_gemini(file_obj, prompt_instructions):
    """
    Starts a Gemini chat session with the uploaded file and the given prompt instructions.
    The 'tools' parameter is passed to the model so that Gemini can call declared functions if needed.
    Returns Gemini’s text output (expected to be a JSON array).
    """
    logging.info("Starting Gemini chat session for data extraction.")
    generation_config = {
        "temperature": 0,
        "top_p": 0.3,
        "top_k": 40,
        "max_output_tokens": 8192,
        "response_mime_type": "text/plain",
    }
    model = genai.GenerativeModel(
        model_name="gemini-2.0-pro-exp-02-05",  # adjust as needed
        generation_config=generation_config,
        system_instruction=prompt_instructions,
    )
    chat_session = model.start_chat(
        history=[
            {
                "role": "user",
                "parts": [
                    file_obj,
                    "Given the following raw financial ledger data, return the extracted transactions as a well-formatted JSON array."
                ]
            }
        ]
    )
    # Use a non-empty string to trigger generation.
    response = chat_session.send_message(" ")
    logging.info("Gemini extraction complete.")
    return response.text
 


def insert_transactions(client_id, transactions, identifier, filename):
    try:
        # Establish a connection to the DuckDB database
        conn = duckdb.connect(database='autogen.duckdb')

        # Dynamically format the table name
        table_name = f"{identifier}_transactions"

        # Prepare data for insertion
        records = []
        
        for t in transactions:
            posting_date = format_date(t.get("date", ""))
            due_date = format_date(t.get("due_date", ""))


            if posting_date:  # Ensure dates are valid before inserting
                records.append({
                "client_id": client_id,
                "date": posting_date,
                "particulars": t.get("particulars", ""),
                "vch_type": t.get("vch_type", ""),
                "vch_no": t.get("vch_no", ""),
                "debit": t.get("debit", 0.00),
                "credit": t.get("credit", 0.00),
                "transaction_num": t.get("transaction_num", ""),
                "due_date":due_date,
                "balance_due": t.get("balance_due", 0.00),
                "cumulative_balance": t.get("cumulative_balance", 0.00),
                "file_name": filename
            })

        if records:
            # Convert records to a Pandas DataFrame
            df = pd.DataFrame(records)

            # Insert DataFrame into DuckDB
            conn.execute(f"""
                INSERT INTO {table_name} (client_id, transaction_num, date, due_date, particulars, debit, credit, balance_due, cumulative_balance, file_name)
                SELECT client_id, transaction_num, date, due_date, particulars, debit, credit, balance_due, cumulative_balance, file_name FROM df
            """)

            print(f"{len(records)} transactions inserted successfully.")
        else:
            print("No valid transactions to insert.")

        # Close the connection
        conn.close()

    except duckdb.Error as err:
        print(f"Error: {err}")


def read_csv(
    file_path: str,
    client_id: int,
    identifier:str,
    filename:str
) -> pd.DataFrame:
    try:
        # Read the CSV file
        df = pd.read_csv(file_path)

        json_content = df.to_string()
        with open("outcsv.txt","w") as f:
            f.write(json_content)
        response = extract_data_with_gemini(json_content, prompt_instruction)
        data = clean_and_parse_chat_response(response)
        
        insert_transactions(client_id, data,identifier,filename)
        return "inserterd"
    except Exception as e:
        raise ValueError(f"Failed to read csv file: {str(e)}")


# Create the PDF reading tool
read_csv_tool = FunctionTool(
    func=read_csv,
    description="Read a csv file, extract text as df for further processing",
    global_imports=[
        "pandas",
        ImportFromModule("typing", ("Optional", "List", "Tuple"))
    ]
)

# read_csv(rf"C:\Users\m28_2\workspace\agentchatV2\testingDocs\csvutf8.csv",2,"client","sddsdd")