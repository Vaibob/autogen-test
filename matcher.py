import duckdb
from autogen_core.tools import FunctionTool

def match(client_id: int):
    # Setup DuckDB connection (adjust the database path as needed)
    conn = duckdb.connect(database='autogen.duckdb', read_only=False)
    cursor = conn.cursor()

    try:
        # Retrieve transactions for the given client_id from both tables
        cursor.execute("SELECT * FROM client_transactions WHERE client_id = ?", (client_id,))
        client_rows = cursor.fetchall()
        client_columns = [desc[0] for desc in cursor.description]
        client_txs = [dict(zip(client_columns, row)) for row in client_rows]

        cursor.execute("SELECT * FROM vendor_transactions WHERE client_id = ?", (client_id,))
        vendor_rows = cursor.fetchall()
        vendor_columns = [desc[0] for desc in cursor.description]
        vendor_txs = [dict(zip(vendor_columns, row)) for row in vendor_rows]

        # Keep track of vendor transactions that have been matched
        matched_vendor_indices = set()

        # Process each client transaction for matching
        for client_tx in client_txs:
            match_found = False
            client_date = client_tx['date']
            # Ensure particulars is not null
            client_particulars = client_tx['particulars'] if client_tx['particulars'] is not None else ""

            # Matching based on client credit against vendor debit
            if client_tx.get('credit') and client_tx['credit'] > 0:
                amount = client_tx['credit']
                for idx, vendor_tx in enumerate(vendor_txs):
                    if idx in matched_vendor_indices:
                        continue
                    if (vendor_tx['date'] == client_date and 
                        vendor_tx.get('debit') and vendor_tx['debit'] == amount):
                        vendor_particulars = vendor_tx['particulars'] if vendor_tx['particulars'] is not None else ""
                        combined_file_name = f"{client_tx['file_name']} | {vendor_tx['file_name']}"
                        particulars = f"{client_particulars} | {vendor_particulars}"
                        insert_query = """
                            INSERT INTO matching_transactions 
                            (client_id, date_client, date_vendor, Debit_client, Credit_client, Debit_vendor, Credit_vendor, file_ref, file_name, particulars)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """
                        # insert_recon_query = """
                        #     INSERT INTO reconciling 
                        #     (client_id, date_client, date_vendor, Debit_client, Credit_client, Debit_vendor, Credit_vendor, file_ref, file_name, particulars, remarks)
                        #     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        # """
                        insert_data = (
                            client_id,
                            client_date, vendor_tx['date'],
                            client_tx['debit'], client_tx['credit'],
                            vendor_tx['debit'], vendor_tx['credit'],
                            "both",  # file_ref for a match
                            combined_file_name,
                            particulars
                        )
                        # insert_recon_data = (
                        #     client_id,
                        #     client_date, vendor_tx['date'],
                        #     client_tx['debit'], client_tx['credit'],
                        #     vendor_tx['debit'], vendor_tx['credit'],
                        #     "both",  # file_ref for a match
                        #     combined_file_name,
                        #     particulars,
                        #     "one on one"
                        # )
                        cursor.execute(insert_query, insert_data)
                        # cursor.execute(insert_recon_query, insert_recon_data)
                        conn.commit()
                        matched_vendor_indices.add(idx)
                        match_found = True
                        break

            # Matching based on client debit against vendor credit
            elif client_tx.get('debit') and client_tx['debit'] > 0:
                amount = client_tx['debit']
                for idx, vendor_tx in enumerate(vendor_txs):
                    if idx in matched_vendor_indices:
                        continue
                    if (vendor_tx['date'] == client_date and 
                        vendor_tx.get('credit') and vendor_tx['credit'] == amount):
                        vendor_particulars = vendor_tx['particulars'] if vendor_tx['particulars'] is not None else ""
                        combined_file_name = f"{client_tx['file_name']} | {vendor_tx['file_name']}"
                        particulars = f"{client_particulars} | {vendor_particulars}"
                        insert_query = """
                            INSERT INTO matching_transactions 
                            (client_id, date_client, date_vendor, Debit_client, Credit_client, Debit_vendor, Credit_vendor, file_ref, file_name, particulars)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """
                        # insert_recon_query = """
                        #     INSERT INTO reconciling 
                        #     (client_id, date_client, date_vendor, Debit_client, Credit_client, Debit_vendor, Credit_vendor, file_ref, file_name, particulars, remarks)
                        #     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        # """
                        insert_data = (
                            client_id,
                            client_date, vendor_tx['date'],
                            client_tx['debit'], client_tx['credit'],
                            vendor_tx['debit'], vendor_tx['credit'],
                            "both",  # file_ref for a match
                            combined_file_name,
                            particulars
                        )
                        # insert_recon_data = (
                        #     client_id,
                        #     client_date, vendor_tx['date'],
                        #     client_tx['debit'], client_tx['credit'],
                        #     vendor_tx['debit'], vendor_tx['credit'],
                        #     "both",  # file_ref for a match
                        #     combined_file_name,
                        #     particulars,
                        #     "one on one"
                        # )
                        cursor.execute(insert_query, insert_data)
                        # cursor.execute(insert_recon_query, insert_recon_data)
                        conn.commit()
                        matched_vendor_indices.add(idx)
                        match_found = True
                        break

            # If no matching vendor transaction is found for the client record, insert it as non-matching
            if not match_found:
                insert_query = """
                    INSERT INTO non_matching_transactions
                    (client_id, date_client, Debit_client, Credit_client, file_ref, file_name, particulars)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                insert_data = (
                    client_id,
                    client_date,
                    client_tx['debit'], client_tx['credit'],
                    "client",  # file_ref is client in non-matching case
                    client_tx['file_name'],
                    client_particulars
                )
                cursor.execute(insert_query, insert_data)
                conn.commit()

        # Process vendor transactions that remain unmatched
        for idx, vendor_tx in enumerate(vendor_txs):
            if idx not in matched_vendor_indices:
                vendor_particulars = vendor_tx['particulars'] if vendor_tx['particulars'] is not None else ""
                insert_query = """
                    INSERT INTO non_matching_transactions
                    (client_id, date_vendor, Debit_vendor, Credit_vendor, file_ref, file_name, particulars)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """
                insert_data = (
                    client_id,
                    vendor_tx['date'],
                    vendor_tx['debit'], vendor_tx['credit'],
                    "vendor",  # file_ref is vendor in non-matching case
                    vendor_tx['file_name'],
                    vendor_particulars
                )
                cursor.execute(insert_query, insert_data)
                conn.commit()

    except Exception as err:
        print("Error:", err)
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

# Example usage:
matcher_tool = FunctionTool(
    func=match,
    description="Generates Client ID",
    global_imports=[
        "duckdb",
    ]
)


# match(13)