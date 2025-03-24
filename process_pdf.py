import easyocr
import json
import os
import base64
import google.generativeai as genai
from autogen_core.tools import FunctionTool
# import mysql.connector
import re
from datetime import datetime
import fitz
import duckdb
import concurrent.futures
import pandas as pd
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

genai.configure(api_key="AIzaSyDH2qvOFEYxVQHQQXhZHfsiM0LQDqNe788")
UpdatedPrompt = """
You are a specialized financial document parser. Your task is to use the OCR extract information (words and their coordinates) from a company ledger document and reconstruct it into a table, then format it into a structured JSON as specified below. Follow these specific guidelines and extract the data:

Header Information:
- Company name
- Complete address (maintain line breaks with \n)
- Contact number
- Email address
- Account name
- Account type
- Period of statement
- Page number

Transaction Entries:
For each transaction entry, extract all ledger records including Opening and Closing Balance but skip 'Carried over' and 'Brought Forward' records in transactions json. Extract the following:
- Date (in DD-MMM-YY format) (take value from OCR)
- Particulars (full description which may contain particulars name, ref number, validity days, split among different GST rates; amounts mentioned should be ignored and not marked as new transactions but clubbed into one transaction)(sometimes its values could be spread across neighbouring column, but it should be mentioned only in particulars not in other columns) (interpret the value from the image instead of OCR)
- Voucher number (if present) (Can also be identified as Vendor Reference No or BillNumbers) (It may be alphanumeric like 'XX-#*', so ensure alphabets with it are included. Take the entire value for it, DO not miss out on the alphabets in it) (interpret the value from the image instead of OCR)
- Voucher type (if present) (it will be under voucher type column, or a column which describes the type of transaction; ignore any amounts) ( if the font is too small, you can interpret the text instead of relying on OCR, because smaller text are tend to be misinterpreted by OCR)(interpret the value from the image instead of OCR)
- Debit amount (if present) (It will be only under debit column for sure, please check carefully)(Use the value from OCR data) 
- Credit amount (if present) (It will be only under credit column for sure, please check carefully)(use the value from OCR data)

Strictly maintian the JSON structure do not modify the structure, fetch the values based on the above mentioned rules and fill the JSON structure accordingly.:
{
    "company": "",
    "address": "",
    "contact": "",
    "email": "",
    "account": "",
    "account_type": "",
    "period": "",
    "page": number,
    "transactions": [
        {
            "date": "",
            "particulars": "",
            "vch_type": "",
            "vch_no": number,
            "debit": number,
            "credit": number
        }
    ]
}

Important Parsing Rules:
- Maintain all numerical values as numbers, not strings
- Keep empty string for missing values; in case of debit or credit, keep it as 0
- Ensure Debit and Credit amount values do not get swapped and present the OCR data as numeric value for example if OCR data read is '10,00,000.00' represent it as 1000000.00, i see you are representing with extra zero. Do not include extra 0.
- Format amounts as decimal numbers
- Preserve the exact order of transactions as they appear in the image. The OCR extract is also in the order of the transaction, so use it if needed
- Return only the JSON output without any additional text or explanations

Prioritize Explicit Dates:
If a transaction already has a specific date provided, retain that date as is.
Do not modify, infer, or overwrite the date for a transaction that already has a valid date.

Only Use Past Dates:
For each transaction with a missing date, look at the previous lines in the ocr extract where there is a date mentioned use that date.
Do not use or infer dates from any transactions that occur later in the sequence, even if they are close.

Assign the Last Available Date:
Assign the most recent past date to the transaction with the missing date.
If there are multiple consecutive transactions with missing dates, they all inherit the same most recent past date.

Do Not Use Future Dates:
Under no circumstances should a transaction with a missing date inherit a date from a future transaction.
"""

def upload_to_gemini(path, mime_type=None):
  """Uploads the given file to Gemini.
  See https://ai.google.dev/gemini-api/docs/prompting_with_media
  """
  file = genai.upload_file(path, mime_type=mime_type)
  print(f"Uploaded file '{file.display_name}' as: {file.uri}")
  return file


def image_to_json(image_path):
    reader = easyocr.Reader(['en'])
    results = reader.readtext(image_path)
    extracted_data = [{"text": text, "x": int(bbox[0][0]), "y": int(bbox[0][1])} for (bbox, text, prob) in results]
    output_json = {"words": extracted_data}
    json_filename = os.path.splitext(os.path.basename(image_path))[0] + ".json"
    with open(json_filename, "w") as json_file:
        json.dump(output_json, json_file, indent=4)
    return output_json

def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


initial_files=[
    encode_image("./initialUploads/mortech1.png"),#not used
    encode_image("./initialUploads/mortech2.png"),#not used
    encode_image("./initialUploads/s1.png"),
    encode_image("./initialUploads/uv.png"),
    encode_image("./initialUploads/uv2.png"),
    encode_image("./initialUploads/kp.png"),
    ]

with open("./initialUploads/mt1.json","r") as f:
    mortech1=json.load(f)["words"]

with open("./initialUploads/mt2.json","r") as f:
    mortech2=json.load(f)["words"]

with open("./initialUploads/s1.json","r") as f:
    s1=json.load(f)["words"]

with open("./initialUploads/uv.json","r") as f:
    uv=json.load(f)["words"]

with open("./initialUploads/uv2.json","r") as f:
    uv2=json.load(f)["words"]

with open("./initialUploads/kp.json","r") as f:
    kp=json.load(f)["words"]

def create_chat_session(image_path, ocr_transcript):
    generation_config = {
        "temperature": 0,
        "top_p": 0.3,
        "top_k": 40,
        "max_output_tokens": 8192,
        "response_mime_type": "text/plain",
    }

    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash-thinking-exp-01-21",
        generation_config=generation_config,
        system_instruction=UpdatedPrompt,
    )

    chat = model.start_chat(
        history=[
            {
                "role":"user",
                "parts":[{"mime_type": "image/png", "data":initial_files[2]},f"here is data for the ocr extract:{s1}, and the image of the page.\nIn case of records of this format, Make sure the dates are correctly assigned to transactions, that is The dates for a blank record should be the previous record's date and not the next record's date. And the particulars are more than one line, it should not be considered as different transactions, the particulats all should be clubbed together as one transaction"]
            },
            {
                "role":"model",
                "parts": ["```json\n{\n\"company\": \"SANKET POLY PACK PVT.LTD. 23-24\",\n\"address\": \"Plot No. 833, Nr. GEB Sub Station; Bavla Rajkot\\nHighway , Kerala GIDC , Dist- Ahmedabad\\nGujarat - 382220, India\",\n\"contact\": \"\",\n\"email\": \"\",\n\"account\": \"J PLASTALLOY PVT LTD\",\n\"account_type\": \"Ledger Account\",\n\"period\": \"1-Apr-2024 to 30-Sep-2024\",\n\"page\": 1,\n\"transactions\": [\n{\n\"date\": \"9-Apr-2024\",\n\"particulars\": \"Dr (as per details)\\nRaw Material Purchase\\nCGST A/c\\nS GST A/C\",\n\"vch_type\": \"Raw Material Purchase\",\n\"vch_no\": \"4\",\n\"debit\": 0,\n\"credit\": 365800.00\n},\n{\n\"date\": \"9-Apr-2024\",\n\"particulars\": \"Cr TDS On Purchase 194 Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": \"50\",\n\"debit\": 310.00,\n\"credit\": 0\n},\n{\n\"date\": \"10-Apr-2024\",\n\"particulars\": \"Dr (as per details)\\nRaw Material Purchase\\nCGST AC\\nS GST AC\",\n\"vch_type\": \"Raw Material Purchase\",\n\"vch_no\": \"6\",\n\"debit\": 0,\n\"credit\": 118000.00\n},\n{\n\"date\": \"10-Apr-2024\",\n\"particulars\": \"Cr TDS On Purchase 194 Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": \"51\",\n\"debit\": 100.00,\n\"credit\": 0\n},\n{\n\"date\": \"15-Apr-2024\",\n\"particulars\": \"Dr (as per details)\\nRaw Material Purchase\\nCGST AC\\nS GST AC\",\n\"vch_type\": \"Raw Material Purchase\",\n\"vch_no\": \"11\",\n\"debit\": 0,\n\"credit\": 204140.00\n},\n{\n\"date\": \"23-Apr-2024\",\n\"particulars\": \"Cr TDS On Purchase 194 Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": \"86\",\n\"debit\": 173.00,\n\"credit\": 0\n},\n{\n\"date\": \"23-Apr-2024\",\n\"particulars\": \"Cr HDFC BANK LTD - CC Account\",\n\"vch_type\": \"Payment\",\n\"vch_no\": \"130\",\n\"debit\": 687357.00,\n\"credit\": 0\n},\n{\n\"date\": \"27-Apr-2024\",\n\"particulars\": \"Dr (as per details)\\nRaw Material Purchase\\nCGST A/C\\nS GST A/C\",\n\"vch_type\": \"Raw Material Purchase\",\n\"vch_no\": \"20\",\n\"debit\": 0,\n\"credit\": 605340.00\n},\n{\n\"date\": \"27-Apr-2024\",\n\"particulars\": \"Cr TDS On Purchase 194 Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": \"93\",\n\"debit\": 513.00,\n\"credit\": 0\n},\n{\n\"date\": \"30-Apr-2024\",\n\"particulars\": \"Dr (as per details)\\nRaw Material Purchase\\nCGST A/C\\nS GST A/C\",\n\"vch_type\": \"Raw Material Purchase\",\n\"vch_no\": \"29\",\n\"debit\": 0,\n\"credit\": 489700.00\n},\n{\n\"date\": \"30-Apr-2024\",\n\"particulars\": \"Cr TDS On Purchase 194 Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": \"106\",\n\"debit\": 415.00,\n\"credit\": 0\n},\n{\n\"date\": \"6-May-2024\",\n\"particulars\": \"Dr (as per details)\\nRaw Material Purchase\\nCGST A/C\\nS GST A/C\",\n\"vch_type\": \"Raw Material Purchase\",\n\"vch_no\": \"31\",\n\"debit\": 0,\n\"credit\": 182900.00\n},\n{\n\"date\": \"6-May-2024\",\n\"particulars\": \"Cr TDS On Purchase 194 Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": \"150\",\n\"debit\": 155.00,\n\"credit\": 0\n},\n{\n\"date\": \"6-May-2024\",\n\"particulars\": \"Cr HDFC BANK LTD : CC Account\",\n\"vch_type\": \"Payment\",\n\"vch_no\": \"175\",\n\"debit\": 604827.00,\n\"credit\": 0\n},\n{\n\"date\": \"13-May-2024\",\n\"particulars\": \"Cr HDFC BANK LTD : CC Account\",\n\"vch_type\": \"Payment\",\n\"vch_no\": \"241\",\n\"debit\": 489285.00,\n\"credit\": 0\n},\n{\n\"date\": \"20-May-2024\",\n\"particulars\": \"Cr HDFC BANK LTD - CC Account\",\n\"vch_type\": \"Payment\",\n\"vch_no\": \"265\",\n\"debit\": 182745.00,\n\"credit\": 0\n},\n{\n\"date\": \"8-Jun-2024\",\n\"particulars\": \"Dr (as per details)\\nRaw Material Purchase\\nCGST A/C\\nS GST A/C\",\n\"vch_type\": \"Raw Material Purchase\",\n\"vch_no\": \"53\",\n\"debit\": 0,\n\"credit\": 403560.00\n},\n{\n\"date\": \"8-Jun-2024\",\n\"particulars\": \"Cr TDS On Purchase 194 Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": \"237\",\n\"debit\": 342.00,\n\"credit\": 0\n},\n{\n\"date\": \"14-Jun-2024\",\n\"particulars\": \"Cr HDFC BANK LTD - CC Account\",\n\"vch_type\": \"Payment\",\n\"vch_no\": \"404\",\n\"debit\": 403218.00,\n\"credit\": 0\n}\n]\n}\n```",
                ],
            },
            {
                "role":"user",
                "parts":[{"mime_type": "image/png", "data":initial_files[3]},f"use the ocr extracts:{uv} and the image,and strictly use credit and debit values(i.e Numerical values~Amount. Dont get confused with consecutive zeros, use the same value from OCR extract,convert it into decimal point value instead of string) from OCR. For other Field values you can use the image to interpret if needed but not for Credit/Debit/Date. if the date is null or none or missing in a transaction, it means that the transaction happens at the previous record's mentioned date. So in that case look back at OCR extracts and check for the date in previous record and use it here, And do not look up on next transaction's date. And dont leave that date as null"]
            },
            {
                "role":"model",
                "parts": [
                    "```json\n{\n\"company\": \"Unovel Industries Pvt. Ltd:\",\n\"address\": \"Survey No. 188/2/2,\\nVillage Luhari;\\nSilvassa\",\n\"contact\": "",\n\"email\": \"fibcsales@unovelpackcom\",\n\"account\": \"J J PLASTALLOY PVT LTD\",\n\"account_type\": \"Ledger Account\",\n\"period\": \"1-Apr-24 to 26-Aug-24\",\n\"page\": 1,\n\"transactions\": [\n{\n\"date\": \"1-Apr-24\",\n\"particulars\": \"Opening Balance\",\n\"vch_type\": \"\",\n\"vch_no\": \"\",\n\"debit\": 0,\n\"credit\": 13884168.09\n},\n{\n\"date\": \"1-Apr-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24000007\",\n\"debit\": 0,\n\"credit\": 223020.00\n},\n{\n\"date\": \"1-Apr-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 2,\n\"debit\": 189.00,\n\"credit\": 0\n},\n{\n\"date\": \"2-Apr-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 2,\n\"debit\": 1500000.00,\n\"credit\": 0\n},\n{\n\"date\": \"10-Apr-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 145,\n\"debit\": 1603080.00,\n\"credit\": 0\n},\n{\n\"date\": \"17-Apr-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 237,\n\"debit\": 927048.00,\n\"credit\": 0\n},\n{\n\"date\": \"18-Apr-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24000445\",\n\"debit\": 0,\n\"credit\": 162262.00\n},\n{\n\"date\": \"18-Apr-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 60,\n\"debit\": 138.00,\n\"credit\": 0\n},\n{\n\"date\": \"24-Apr-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 360,\n\"debit\": 1000000.00,\n\"credit\": 0\n},\n{\n\"date\": \"24-Apr-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG24000600\",\n\"debit\": 0,\n\"credit\": 196470.00\n},\n{\n\"date\": \"24-Apr-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 95,\n\"debit\": 167.00,\n\"credit\": 0\n},\n{\n\"date\": \"24-Apr-24\",\n\"particulars\": \"Deemed Purchase 18%\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG24000591\",\n\"debit\": 0,\n\"credit\": 598260.00\n},\n{\n\"date\": \"24-Apr-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG24000592\",\n\"debit\": 0,\n\"credit\": 272568.00\n},\n{\n\"date\": \"24-Apr-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 97,\n\"debit\": 507.00,\n\"credit\": 0\n},\n{\n\"date\": \"24-Apr-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 96,\n\"debit\": 231.00,\n\"credit\": 0\n},\n{\n\"date\": \"27-Apr-24\",\n\"particulars\": \"Deemed Purchase 18%\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24000695\",\n\"debit\": 0,\n\"credit\": 917332.00\n},\n{\n\"date\": \"27-Apr-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 104,\n\"debit\": 777.00,\n\"credit\": 0\n},\n{\n\"date\": \"30-Apr-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 425,\n\"debit\": 792572.00,\n\"credit\": 0\n},\n{\n\"date\": \"30-Apr-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24000765\",\n\"debit\": 0,\n\"credit\": 28261.00\n},\n{\n\"date\": \"30-Apr-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 177,\n\"debit\": 24.00,\n\"credit\": 0\n},\n{\n\"date\": \"7-May-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 648,\n\"debit\": 766911.00,\n\"credit\": 0\n},\n{\n\"date\": \"15-May-24\",\n\"particulars\": \"Deemed Purchase 18%\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24001124\",\n\"debit\": 0,\n\"credit\": 997100.00\n},\n{\n\"date\": \"15-May-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 318,\n\"debit\": 66.00,\n\"credit\": 0\n},\n{\n\"date\": \"15-May-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 317,\n\"debit\": 845.00,\n\"credit\": 0\n},\n{\n\"date\": \"15-May-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24001125\",\n\"debit\": 0,\n\"credit\": 77821.00\n},\n{\n\"date\": \"17-May-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24001186\",\n\"debit\": 0,\n\"credit\": 72098.00\n},\n{\n\"date\": \"17-May-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 359,\n\"debit\": 61.00,\n\"credit\": 0\n},\n{\n\"date\": \"17-May-24\",\n\"particulars\": \"Deemed Purchase 18%\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24001187\",\n\"debit\": 0,\n\"credit\": 358956.00\n},\n{\n\"date\": \"17-May-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 360,\n\"debit\": 304.00,\n\"credit\": 0\n},\n{\n\"date\": \"20-May-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24001247\",\n\"debit\": 0,\n\"credit\": 100200.00\n},\n{\n\"date\": \"20-May-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 378,\n\"debit\": 85.00,\n\"credit\": 0\n},\n{\n\"date\": \"25-May-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24001435\",\n\"debit\": 0,\n\"credit\": 250868.00\n},\n{\n\"date\": \"25-May-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 421,\n\"debit\": 213.00,\n\"credit\": 0\n},\n{\n\"date\": \"27-May-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 817,\n\"debit\": 1461970.00,\n\"credit\": 0\n},\n{\n\"date\": \"27-May-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24001459\",\n\"debit\": 0,\n\"credit\": 96270.00\n},\n{\n\"date\": \"27-May-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 460,\n\"debit\": 82.00,\n\"credit\": 0\n},\n{\n\"date\": \"29-May-24\",\n\"particulars\": \"Deemed Purchase 18%\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-24001553\",\n\"debit\": 0,\n\"credit\": 1336114.00\n},\n{\n\"date\": \"29-May-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 464,\n\"debit\": 1132.00,\n\"credit\": 0\n},\n{\n\"date\": \"4-Jun-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 953,\n\"debit\": 1342634.00,\n\"credit\": 0\n},\n{\n\"date\": \"13-Jun-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-100311\",\n\"debit\": 0,\n\"credit\": 753843.00\n},\n{\n\"date\": \"13-Jun-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-100309\",\n\"debit\": 0,\n\"credit\": 33512.00\n}\n]\n}\n```",
                ],
            },
            {
                "role":"user",
                "parts":[{"mime_type": "image/png", "data":initial_files[4]}, f"Here is the OCR Extracted data: {uv2}, Make sure the dates are interpreted correctly and dont do any mistakes"],
            },
            {
                "role": "model",
                "parts": [
                    "```json\n{\n\"company\": \"Unovel Industries Pvt: Ltd:\",\n\"address\": \"\",\n\"contact\": \"\",\n\"email\": \"\",\n\"account\": \"J J PLASTALLOY PVT LTD\",\n\"account_type\": \"Ledger Account\",\n\"period\": \"1-Apr-24 to 26-Aug-24\",\n\"page\": 2,\n\"transactions\": [\n{\n\"date\": \"13-Jun-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 662,\n\"debit\": 639.00,\n\"credit\": 0\n},\n{\n\"date\": \"13-Jun-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 661,\n\"debit\": 28.00,\n\"credit\": 0\n},\n{\n\"date\": \"15-Jun-24\",\n\"particulars\": \"Purchase Interstate GST - 18 - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-100403\",\n\"debit\": 0,\n\"credit\": 24780.00\n},\n{\n\"date\": \"17-Jun-24\",\n\"particulars\": \"Purchase Interstate GST - 18 - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-100435\",\n\"debit\": 0,\n\"credit\": 24426.00\n},\n{\n\"date\": \"17-Jun-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 696,\n\"debit\": 21.00,\n\"credit\": 0\n},\n{\n\"date\": \"17-Jun-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 688,\n\"debit\": 21.00,\n\"credit\": 0\n},\n{\n\"date\": \"26-Jun-24\",\n\"particulars\": \"HDFC BANK LTD-CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 986,\n\"debit\": 893918.00,\n\"credit\": 0\n},\n{\n\"date\": \"4-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18 - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-100965\",\n\"debit\": 0,\n\"credit\": 221309.00\n},\n{\n\"date\": \"4-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1035,\n\"debit\": 188.00,\n\"credit\": 0\n},\n{\n\"date\": \"9-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18 - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101125\",\n\"debit\": 0,\n\"credit\": 306800.00\n},\n{\n\"date\": \"9-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 892,\n\"debit\": 260.00,\n\"credit\": 0\n},\n{\n\"date\": \"13-Jul-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 1448,\n\"debit\": 900000.00,\n\"credit\": 0\n},\n{\n\"date\": \"15-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18 - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101303\",\n\"debit\": 0,\n\"credit\": 28993.00\n},\n{\n\"date\": \"15-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 951,\n\"debit\": 25.00,\n\"credit\": 0\n},\n{\n\"date\": \"15-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18 - 18\",\n\"vch_type\": \"PURCHASE CST\",\n\"vch_no\": \"DG-101302\",\n\"debit\": 0,\n\"credit\": 13924.00\n},\n{\n\"date\": \"15-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 952,\n\"debit\": 12.00,\n\"credit\": 0\n},\n{\n\"date\": \"16-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18 - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101326\",\n\"debit\": 0,\n\"credit\": 96064.00\n},\n{\n\"date\": \"16-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 995,\n\"debit\": 81.00,\n\"credit\": 0\n},\n{\n\"date\": \"17-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101357\",\n\"debit\": 0,\n\"credit\": 30326.00\n},\n{\n\"date\": \"17-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101356\",\n\"debit\": 0,\n\"credit\": 115970.00\n},\n{\n\"date\": \"17-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 997,\n\"debit\": 26.00,\n\"credit\": 0\n},\n{\n\"date\": \"17-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 996,\n\"debit\": 98.00,\n\"credit\": 0\n},\n{\n\"date\": \"18-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101386\",\n\"debit\": 0,\n\"credit\": 158002.00\n},\n{\n\"date\": \"18-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 998,\n\"debit\": 134.00,\n\"credit\": 0\n},\n{\n\"date\": \"18-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101387\",\n\"debit\": 0,\n\"credit\": 24544.00\n},\n{\n\"date\": \"18-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 999,\n\"debit\": 21.00,\n\"credit\": 0\n},\n{\n\"date\": \"25-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101551\",\n\"debit\": 0,\n\"credit\": 207090.00\n},\n{\n\"date\": \"25-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1019,\n\"debit\": 1034.00,\n\"credit\": 0\n},\n{\n\"date\": \"25-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1018,\n\"debit\": 176.00,\n\"credit\": 0\n},\n{\n\"date\": \"25-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE CST\",\n\"vch_no\": \"DG-101550\",\n\"debit\": 0,\n\"credit\": 1220533.00\n},\n{\n\"date\": \"26-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101606\",\n\"debit\": 0,\n\"credit\": 1071735.00\n},\n{\n\"date\": \"26-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1076,\n\"debit\": 908.00,\n\"credit\": 0\n},\n{\n\"date\": \"31-Jun-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 1540,\n\"debit\": 927374.00,\n\"credit\": 0\n},\n{\n\"date\": \"31-Jul-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101759\",\n\"debit\": 0,\n\"credit\": 291932.00\n},\n{\n\"date\": \"31-Jul-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1143,\n\"debit\": 247.00,\n\"credit\": 0\n},\n{\n\"date\": \"5-Aug-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 1731,\n\"debit\": 837301.00,\n\"credit\": 0\n},\n{\n\"date\": \"5-Aug-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101882\",\n\"debit\": 0,\n\"credit\": 254172.00\n},\n{\n\"date\": \"5-Aug-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1253,\n\"debit\": 215.00,\n\"credit\": 0\n},\n{\n\"date\": \"6-Aug-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101895\",\n\"debit\": 0,\n\"credit\": 58410.00\n},\n{\n\"date\": \"6-Aug-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1254,\n\"debit\": 50.00,\n\"credit\": 0\n},\n{\n\"date\": \"8-Aug-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-101967\",\n\"debit\": 0,\n\"credit\": 601387.00\n},\n{\n\"date\": \"8-Aug-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1244,\n\"debit\": 510.00,\n\"credit\": 0\n},\n{\n\"date\": \"12-Aug-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE CST\",\n\"vch_no\": \"DG-102065\",\n\"debit\": 0,\n\"credit\": 1328238.00\n},\n{\n\"date\": \"12-Aug-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1294,\n\"debit\": 1126.00,\n\"credit\": 0\n},\n{\n\"date\": \"13-Aug-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 1853,\n\"debit\": 931410.09,\n\"credit\": 0\n},\n{\n\"date\": \"14-Aug-24\",\n\"particulars\": \"Purchase Interstate GST - 18\",\n\"vch_type\": \"PURCHASE GST\",\n\"vch_no\": \"DG-102123\",\n\"debit\": 0,\n\"credit\": 398191.00\n},\n{\n\"date\": \"14-Aug-24\",\n\"particulars\": \"TDS ON PURCHASE U/S 194Q\",\n\"vch_type\": \"Journal\",\n\"vch_no\": 1329,\n\"debit\": 337.00,\n\"credit\": 0\n},\n{\n\"date\": \"23-Aug-24\",\n\"particulars\": \"HDFC BANK LTD - CC A/c\",\n\"vch_type\": \"Payment\",\n\"vch_no\": 1937,\n\"debit\": 581258.00,\n\"credit\": 0\n}\n]\n}\n```",
                ],
            },
            {
                "role":"user",
                "parts":[{"mime_type": "image/png", "data":initial_files[5]}, f"Here is the OCR Extracted data: {kp}, Which has a new column Balance, do not get confused to it, Strictly follow the Debit and Credit Column values and extract those correctly without getting their values swapped. Extract transactional values even if there is some after closing balance. Do not miss out any transaction The image is also attached along."],
            },
            {
                "role": "model",
                "parts": ["```json\n{\n    \"company\": \"KPT Piping System Pvt. Ltd_\",\n    \"address\": \"122,/69, Central Hope Town\\nSelaqui Industrial Area, Sahaspur\\nSelaqui; Dehradun-248197\",\n    \"contact\": \"\",\n    \"email\": \"\",\n    \"account\": \"JJ Plast Alloy Pvt Ltd  (Guj)\",\n    \"account_type\": \"Ledger Account\",\n    \"period\": \"1-Apr-23 to 6-Sep-24\",\n    \"page\": 1,\n    \"transactions\": [\n        {\n            \"date\": \"8-Apr-23\",\n            \"particulars\": \"Dr GST  Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23000148\",\n            \"debit\": 0,\n            \"credit\": 165200.00\n        },\n        {\n            \"date\": \"20-Apr-23\",\n            \"particulars\": \"Cr   Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"273\",\n            \"debit\": 197683.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"22-May-23\",\n            \"particulars\": \"Cr   Axis Bank Limited Cc (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"750\",\n            \"debit\": 169920.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"23-May-23\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23000992\",\n            \"debit\": 0,\n            \"credit\": 163430.00\n        },\n        {\n            \"date\": \"20-Jun-23\",\n            \"particulars\": \"Cr   AxisBank Limited Cc (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"1142\",\n            \"debit\": 165200.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"3-Jul-23\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23001832\",\n            \"debit\": 0,\n            \"credit\": 159300.00\n        },\n        {\n            \"date\": \"19-Jul-23\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23002167\",\n            \"debit\": 0,\n            \"credit\": 159300.00\n        },\n        {\n            \"date\": \"21-Jul-23\",\n            \"particulars\": \"Cr  Axis Bank Limied CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"1586\",\n            \"debit\": 163430.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"22-Aug-23\",\n            \"particulars\": \"Cr   Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"1917\",\n            \"debit\": 159300.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"30-Aug-23\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"Da/23003109\",\n            \"debit\": 0,\n            \"credit\": 159300.00\n        },\n        {\n            \"date\": \"20-Sep-23\",\n            \"particulars\": \"Cr   Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"2401\",\n            \"debit\": 159300.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"4-Oct-23\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23003834\",\n            \"debit\": 0,\n            \"credit\": 63425.00\n        },\n        {\n            \"date\": \"14-Oct-23\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23004094\",\n            \"debit\": 0,\n            \"credit\": 161660.00\n        },\n        {\n            \"date\": \"21-Oct-23\",\n            \"particulars\": \"Cr  Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"2845\",\n            \"debit\": 0,\n            \"credit\": 159300.00\n        },\n        {\n            \"date\": \"28-Oct-23\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23004331\",\n            \"debit\": 0,\n            \"credit\": 161660.00\n        },\n        {\n            \"date\": \"22-Nov-23\",\n            \"particulars\": \"Cr  Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"3371\",\n            \"debit\": 63425.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"21-Dec-23\",\n            \"particulars\": \"Cr   Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"3827\",\n            \"debit\": 161660.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"1-Jan-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23005054\",\n            \"debit\": 0,\n            \"credit\": 161660.00\n        },\n        {\n            \"date\": \"5-Jan-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23005875\",\n            \"debit\": 0,\n            \"credit\": 405920.00\n        },\n        {\n            \"date\": \"20-Jan-24\",\n            \"particulars\": \"Cr   Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"4290\",\n            \"debit\": 161660.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"13-Feb-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23006891\",\n            \"debit\": 0,\n            \"credit\": 162840.00\n        },\n        {\n            \"date\": \"21-Feb-24\",\n            \"particulars\": \"Cr   Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"4706\",\n            \"debit\": 161660.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"21-Feb-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23007076\",\n            \"debit\": 0,\n            \"credit\": 60770.00\n        },\n        {\n            \"date\": \"21-Feb-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23007075\",\n            \"debit\": 0,\n            \"credit\": 162840.00\n        },\n        {\n            \"date\": \"15-Mar-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/23007681\",\n            \"debit\": 0,\n            \"credit\": 60770.00\n        },\n        {\n            \"date\": \"20-Mar-24\",\n            \"particulars\": \"Cr   Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"5148\",\n            \"debit\": 205920.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"4-Apr-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"94\",\n            \"debit\": 0,\n            \"credit\": 182310.00\n        },\n        {\n            \"date\": \"5-Apr-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG24000081\",\n            \"debit\": 0,\n            \"credit\": 162840.00\n        },\n        {\n            \"date\": \"23-Apr-24\",\n            \"particulars\": \"Cr   AxisBank Limited Cc (A/C No 921080045644141) \",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"356\",\n            \"debit\": 362480.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"8-May-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG24000914\",\n            \"debit\": 0,\n            \"credit\": 243080.00\n        },\n        {\n            \"date\": \"17-May-24\",\n            \"particulars\": \"Dr  GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG24001165\",\n            \"debit\": 0,\n            \"credit\": 162840.00\n        },\n        {\n            \"date\": \"22-May-24\",\n            \"particulars\": \"Cr   Axis Bank Limited Cc (AVC No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"844\",\n            \"debit\": 200000.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"5-Jun-24\",\n            \"particulars\": \"Dr  GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/100087\",\n            \"debit\": 0,\n            \"credit\": 243080.00\n        },\n        {\n            \"date\": \"21-Jun-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/100578\",\n            \"debit\": 0,\n            \"credit\": 162840.00\n        },\n        {\n            \"date\": \"24-Jun-24\",\n            \"particulars\": \"Cr   AxisBank Limited Cc (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"1360\",\n            \"debit\": 429890.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"20-Jul-24\",\n            \"particulars\": \"Dr GST Interstate Purchase\",\n            \"vch_type\": \"Purchase\",\n            \"vch_no\": \"DG/101437\",\n            \"debit\": 0,\n            \"credit\": 162840.00\n        },\n        {\n            \"date\": \"24-Jul-24\",\n            \"particulars\": \"Cr   AxisBank Limited Cc (A/C No 921080045644141) \",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"1772\",\n            \"debit\": 405920.00,\n            \"credit\": 0\n        },\n        {\n            \"date\": \"21-Aug-24\",\n            \"particulars\": \"Cr   Axis Bank Limited CC (A/C No 921080045644141)\",\n            \"vch_type\": \"Payment\",\n            \"vch_no\": \"2259\",\n            \"debit\": 405920.00,\n            \"credit\": 0\n        }\n    ]\n}\n```",],
            },
            
        ]
    )
    response=chat.send_message([f"use the ocr extracts:{ocr_transcript} and the image,and strictly use credit and debit values from OCR extract . particulars may contain name, ref number, validity days, split among different GST rates; amounts mentioned should be ignored and It should not marked as new transactions but clubbed into one single transaction; infer particulars value from the image instead of OCR",{"mime_type": "image/png", "data":encode_image(image_path)}])
    # print(response.text)
    return response.text

def clean_and_parse_chat_response(chat_response):
    chat_response = chat_response.replace("```json", "").strip()
    chat_response = chat_response.replace("```", "").strip()
    chat_response = re.sub(r'[\x00-\x1F]+', '', chat_response)

    # Convert JSON string to dictionary
    return json.loads(chat_response)

# Function to convert date format
def format_date(date_str):
    if date_str is None:
        return None  # or handle it as you wish (e.g., return a default date)
    for fmt in ("%d-%b-%Y", "%d-%b-%y", "%d-%m-%Y", "%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    print(f"Invalid date format: {date_str}")
    return None


# Replace these with your MySQL credentials
# DB_CONFIG = {
#     "host": "localhost",
#     "user": "root",
#     "password": "12345678",
#     "database": "autogen"
# }

# Insert transactionsimport mysql.connector



def insert_transactions(client_id, transactions, identifier, filename):
    try:
        # Establish a connection to the DuckDB database
        conn = duckdb.connect(database='autogen.duckdb')

        # Dynamically format the table name
        table_name = f"{identifier}_transactions"

        # Prepare data for insertion
        records = []
        for t in transactions:
            formatted_date = format_date(t["date"])
            if formatted_date:  # Ensure date is valid before inserting
                records.append({
                    "client_id": client_id,
                    "date": formatted_date,
                    "particulars": t.get("particulars", ""),
                    "vch_type": t.get("vch_type", ""),
                    "vch_no": t.get("vch_no", ""),
                    "debit": t.get("debit", 0.00),
                    "credit": t.get("credit", 0.00),
                    "transaction_num": t.get("transaction_num", ""),
                    "due_date": t.get("due_date", None),
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


def pdf_to_images(pdf_path:str)->list:
  pdf_document = fitz.open(pdf_path)
  
  image_paths = []
  for page_num in range(len(pdf_document)):
      page = pdf_document.load_page(page_num)
      pix = page.get_pixmap(matrix=fitz.Matrix(750 / 72, 750 / 72))  # Render at 500 DPI
      image_path = os.path.join(UPLOAD_FOLDER, f"page_{page_num + 1}_{os.path.basename(pdf_path)}.png")
      pix.save(image_path)
      image_paths.append(image_path)
  pdf_document.close()
  return image_paths


def process_pdf(pdf_path:str,client_id:int,identifier:str,filename:str)->str:
    imagepaths=pdf_to_images(pdf_path)
    def process_image(imagepath):
        ocr_result = image_to_json(imagepath)
        ocr_transcript = ocr_result["words"]
        data = clean_and_parse_chat_response(create_chat_session(imagepath, ocr_transcript))
        insert_transactions(client_id, data.get("transactions", []),identifier,filename)

    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        executor.map(process_image, imagepaths)
    return client_id

process_pdf_tool = FunctionTool(
    func=process_pdf,
    description="Perform JSON extraction of data from images of ledger and pushes into db",
    global_imports=[
        "os",
        "easyocr",
        "json",
        "base64",
        "google.generativeai as genai",
        "mysql.connector",
        "re",
        "datetime"
    ]
)


# process_pdf(rf"C:\Users\m28_2\Downloads\JJPL files 3\A.U Industries ahm 24-25.pdf",1,'client','tests')

