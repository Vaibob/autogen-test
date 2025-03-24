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
# genai.configure(api_key="AIzaSyDH2qvOFEYxVQHQQXhZHfsiM0LQDqNe788")
genai.configure(api_key="AIzaSyCfFrtg0ofIMydEz6hgxbieIzUZ9WCHj0U")
# genai.configure(api_key="AIzaSyC1RQrNTJK4vB3WbIa1ip7-Nm6a7mpAnqw")
# genai.configure(api_key="AIzaSyDmt-PWtcH3t4x9W4ehh4822aS0JVpj_Rk")
prompt_instruction ="""1. **Identify Tabular Data:**
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
   - **Date Formatting (Posting Date - Special Handling):**
     - The "Posting Date" column may contain visually inconsistent date formats *within the string*.
     - **Interpret and convert the dates in the "Posting Date" column, adhering to these rules *simultaneously*:**
       - **Separator Rule:**
         - **If the date uses hyphens (`-`) *and* is in the format `yyyy-dd-mm hh:mm:ss`, initially interpret it as `yyyy-dd-mm` (Year-Day-Month). The middle number is always date not month.**
         - **If the date uses slashes (`/`) as separators, initially interpret it as `dd/mm/yyyy`.**
       - **Strict Chronological Order:** The dates *must* be in strict chronological order. Each date must be greater than or equal to the preceding date *within the extracted "Posting Date" column*.
       - **Adjacent Date Comparison:** Use the information from *both preceding and subsequent* dates to resolve ambiguities and confirm the month assignments. If the separator rule leads to a date that violates chronological order, *override the separator rule* and adjust the month to maintain chronological order.
       - **Latest Date Limit:**  Examine the *entire* "Posting Date" column.  No date can be later than the latest valid date found in the column.
       - Convert the correctly interpreted dates to the "dd-MMM-yy" format (e.g., "12-Oct-23").

     - **Specific Examples (Illustrating Inference, assuming these are extracted Posting Dates):**
        - "2024-07-03 00:00:00" -> "07-Mar-24" (Separator rule: yyyy-dd-mm)
        - "2024-11-03 00:00:00" -> "11-Mar-24" (Separator: yyyy-dd-mm)
        - "2024-03-04 00:00:00" -> "03-Apr-24" (Separator rule: yyyy-dd-mm)
        - "29/04/24"    ->  "29-Apr-24" (Separator rule: dd/mm/yyyy)
        - "22/05/24"    ->  "22-May-24" (Separator rule: dd/mm/yyyy)
        - "18/06/24"    ->  "18-Jun-24" (Separator rule: dd/mm/yyyy)
        - "24/06/24"    ->  "24-Jun-24" (Separator rule: dd/mm/yyyy)
        Example set 2:
        - "2024-04-03 00:00:00" -> "04-Mar-24" (separator rule :yyyy-dd-mm)
        - "27/03/24"    -> "27-Mar-24" (separator rule:dd/mm/yyyy)
        - "2024-04-04 00:00:00" -> "04-Apr-24" (separator rule yyyy-dd-mm)
        - "2024-05-04 00:00:00" -> "05-Apr-24" (separator rule yyyy-dd-mm)

    
     - **General Principle:**
       1.  **Separator Rule:**  `yyyy-dd-mm hh:mm:ss` implies `yyyy-dd-mm`; `/` implies `dd/mm/yyyy`. Use this as the *initial* interpretation. Dates with hyphens but *not* in the full timestamp format should be treated as ambiguous, relying on chronological order.
       2.  **Strict Chronological Order:**  This *overrides* the separator rule if necessary.
       3.  **Latest Date Limit:**  No date can be later than the last valid date.
       4.  **Adjacent Date Comparison:**  Use both preceding and subsequent dates to confirm and correct.

   - **Date Formatting (Other Dates):** For other date columns (e.g., "Due Date"), apply the *same rules*: separator-based initial interpretation, strict chronological order (which can override the separator rule), adjacent date comparison, and conversion to "dd-MMM-yy". Do *not* apply the "latest date" constraint unless explicitly stated for that column.

   - **Numeric Fields:**
     - Remove any non-numeric characters (like "INR", commas, parentheses) from the "Debit Amount", "Credit Amount", "Balance Due", and "Cumulative Balance" columns.
     - Convert these cleaned values to floating-point numbers.

   - **Null Handling:** Replace missing values (NaN, empty strings, or cells with only whitespace) with an empty string ("").

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
   - The values for "debit", "credit", "balance_due", and "cumulative_balance" should be numbers (float), not strings.

#### **Output Requirement:**
- The final output should be a **single JSON array** containing all extracted transactions.
"""
#"""
# 1. **Identify Tabular Data:**
#    - Locate the table containing transaction details and extract the following columns:
#      - **Transaction Number**
#      - **Posting Date**
#      - **Due Date**
#      - **Description**
#      - **Debit Amount**
#      - **Credit Amount**
#      - **Balance Due**
#      - **Cumulative Balance**

# 2. **Data Cleaning:**
#    - **Date Formatting (Posting Date - Special Handling):**
#      - **Goal:**  Correctly interpret the dates in the "Posting Date" column, even though they might be written in confusing or inconsistent ways.
#      - **Rule 1: Strict Chronological Order:** The dates are *absolutely* in chronological order, from earliest to latest.  *Never* assume a date is out of order.
#      - **Rule 2: Latest Date Anchor:** The *last* date in the column is a key reference point.  It represents the *latest possible date* in the entire column.

#      - **Step-by-Step Instructions:**
#         1. **Find the Last Date:** Look at the *very last* date in the "Posting Date" column.
#         2. **Determine the Latest Possible Interpretation:**  Figure out the *latest possible* date this last entry could represent.  Consider these possibilities:
#            - If it looks like `dd-mm-yyyy` or `dd/mm/yy`, try interpreting it that way.
#            - If it looks like `mm-dd-yyyy`, try interpreting it that way.
#            - Choose the interpretation that gives you the *latest* possible date.  This is your "latest date anchor."
#         3. **Interpret All Dates (One by One):**
#            - Start with the *first* date in the column.
#            - Look at its format.
#            - **Key Idea:**  Interpret the month and day *in whatever way is necessary* to make the date fit the strict chronological order *and* be earlier than or equal to the "latest date anchor."
#            - Repeat this for *every* date in the column, moving from top to bottom.  Each date *must* be later than or equal to the one before it, and *no* date can be later than the "latest date anchor."
#         4. **Convert to Standard Format:** Once you've figured out the correct month, day, and year for each date, convert it to the "dd-MMM-yy" format (like "12-Oct-23").

#      - **Specific Example (Based on provided image):**
#         - The *last* date is "29/07/24". The latest possible interpretation is "29-Jul-24". This is our anchor.  *No date can be later than July 29th, 2024.*
#         - "29/04/24"    ->  "29-Apr-24"
#         - "05-06-2024"  -> "06-May-24"
#         - "05-09-2024" -> "09-May-24"
#         - "05-10-2024" -> "10-May-24"
#         - "22/05/24"    ->  "22-May-24"
#         - "06-08-2024"  -> "08-Jun-24"
#         - "06-11-2024"  ->  "11-Jun-24"  (*This must be June, not November, because November is later than our July anchor date.*)
#         - "18/06/24"    ->  "18-Jun-24"
#         - "24/06/24"    ->  "24-Jun-24"
#         - "07-08-2024" -> "08-Jul-24"
#         - "18/07/24"    ->  "18-Jul-24"
#         - "23/07/24"    ->  "23-Jul-24"
#         - "29/07/24"    ->  "29-Jul-24"
#         - "29/07/24"    ->  "29-Jul-24"

#      - **Important:** If you're ever unsure about a date, *always* choose the interpretation that keeps the dates in perfect chronological order and doesn't go past the "latest date anchor."

#    - **Date Formatting (Other Dates):** For other date columns (e.g., "Due Date"), convert dates to "dd-MMM-yy" (e.g., "12-Oct-23") if they are in a standard, recognizable format. If they have similar issues to the "Posting Date" column, apply the same chronological inference logic.
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
# prompt_instruction = """
# 1. **Identify Tabular Data:**
#    - Locate the table containing transaction details and extract the following columns:
#      - **Transaction Number**
#      - **Posting Date**
#      - **Due Date**
#      - **Description**
#      - **Debit Amount**
#      - **Credit Amount**
#      - **Balance Due**
#      - **Cumulative Balance**

# 2. **Data Cleaning:**
#    - **Date Formatting (Posting Date - Special Handling):**
#      - The "Posting Date" column in the Excel file may contain visually inconsistent date formats.
#      - **Crucially, assume the dates in the "Posting Date" column are presented in *chronological order*, regardless of their visual appearance.**
#      -  Use this chronological order to *infer* the correct day, month, and year.
#      - Convert the inferred dates to the "dd-MMM-yy" format (e.g., "12-Oct-23").
#      - **Specific Example **: Even though the dates *look* like "04-03-2024", "04-08-2024", etc.,  you should interpret them based on the chronological sequence.  The correct interpretation and conversion should be:
#         - "04-03-2024"  ->  "03-Apr-24"
#         - "04-08-2024"  ->  "08-Apr-24"
#         - "04-10-2024"  ->  "10-Apr-24"
#         - "23/05/24"    ->  "23-May-24"
#         - "23/05/24"    ->  "23-May-24"
#         - "23/05/24"    ->  "23-May-24"
#         - "24/05/24"    ->  "24-May-24"
#         - "15/06/24"    ->  "15-Jun-24"
#         - "19/06/24"    ->  "19-Jun-24"
#         - "26/06/24"    ->  "26-Jun-24"
#         - "07-10-2024"  ->  "10-Jul-24"
#         - "07-12-2024"  ->  "12-Jul-24"
#      - **General Principle:**  Always prioritize the chronological order of the dates in the "Posting Date" column to determine the correct month and day, even if the visual representation is ambiguous or incorrect.

#    - **Date Formatting (Other Dates):** For other date columns (e.g., "Due Date"), convert dates to "dd-MMM-yy" (e.g., "12-Oct-23") if they are in a standard, recognizable format. If they have similar issues to the "Posting Date" column, apply the same chronological inference logic.
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

def clean_and_parse_chat_response(chat_response):
    chat_response = chat_response.replace("```json", "").strip()
    chat_response = chat_response.replace("```", "").strip()
    chat_response = re.sub(r'[\x00-\x1F]+', '', chat_response)

    # Convert JSON string to dictionary
    return json.loads(chat_response)

def format_date(date_str):
    if not date_str :
        return None  # or handle it as you wish (e.g., return a default date)
    for fmt in ("%d-%b-%Y", "%d-%B-%y","%d-%b-%y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    print(f"Invalid date format: {date_str}")
    return None


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
                    "Given the following raw financial ledger data, Return the extracted transactions as a valid JSON array (no extra text or formatting)."
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

# def insert_transactions(client_id, transactions, identifier,filename):
#     try:
#         conn = mysql.connector.connect(**DB_CONFIG)
#         cursor = conn.cursor()

#         # Properly format table name
#         table_name = f"{identifier}_transactions"

#         query = f"""
#        INSERT INTO {table_name} (
#             client_id, transaction_num, date, due_date, 
#             particulars, debit, credit, balance_due, cumulative_balance,file_name
#         ) 
#         VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
#         """

#         records = []
#         for t in transactions:
#             posting_date = format_date(t.get("date", ""))
#             due_date = format_date(t.get("due_date", ""))

#             if posting_date:  # Ensure dates are valid before inserting
#                 records.append((
#                     client_id,
#                     t.get("transaction_num", ""),
#                     posting_date,
#                     due_date,
#                     t.get("particulars", ""),
#                     float(t.get("debit", 0)) if t.get("debit") else 0.00,
#                     float(t.get("credit", 0)) if t.get("credit") else 0.00,
#                     float(t.get("balance_due", 0)) if t.get("balance_due") else 0.00,
#                     float(t.get("cumulative_balance", 0)) if t.get("cumulative_balance") else 0.00,
#                     filename
#                 ))

#         if records:
#             cursor.executemany(query, records)  # Batch insert
#             conn.commit()
#             print(f"{cursor.rowcount} transactions inserted successfully.")
#         else:
#             print("No valid transactions to insert.")

#         cursor.close()
#         conn.close()

#     except mysql.connector.Error as err:
#         print(f"Error: {err}")


def read_excel(
    file_path: str,
    client_id: int,
    identifier:str,
    filename:str,
    sheet_name: Optional[str] = None
) -> pd.DataFrame:
    try:
        # Read the Excel file
        excel_data = pd.read_excel(file_path, sheet_name=sheet_name, thousands=',')

        if isinstance(excel_data, dict):
            first_sheet_name = list(excel_data.keys())[0]  # Get first sheet name
            df = excel_data[first_sheet_name]  # Select first sheet DataFrame
        else:
            df = excel_data  # Already a DataFrame
        load=df
        with open("ot.txt","w") as f:
            f.write(load.to_string())
        # Split the DataFrame into chunks of 50 rows each
        chunk_size = 40
        chunks = [df[i:i + chunk_size] for i in range(0, df.shape[0], chunk_size)]
        i=0
        for chunk in chunks:
            json_content = chunk.to_string()
            # print(i)
            response = extract_data_with_gemini(json_content, prompt_instruction)
            # print(response)
            # i+=1
            # print("response received",i)
            data = clean_and_parse_chat_response(response)
            insert_transactions(client_id, data, identifier, filename)
        return "inserted"
    except Exception as e:
        raise ValueError(f"Failed to read Excel file: {str(e)}")


# Create the PDF reading tool
read_excel_tool = FunctionTool(
    func=read_excel,
    description="Read a excel file, extract text as df for further processing",
    global_imports=[
        "pandas",
        ImportFromModule("typing", ("Optional", "List", "Tuple"))
    ]
)
# read_excel(rf"C:\Users\m28_2\workspace\agentchatV3\testingDocs\sample.xlsx",2,"client","sample")