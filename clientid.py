import duckdb
from autogen_core.tools import FunctionTool

DB_CONFIG = {
    "database": "autogen.duckdb"
}

def get_client(dummy: str) -> int:
    try:
        conn = duckdb.connect(database=DB_CONFIG["database"])
        cursor = conn.cursor()
        # Create table if it doesn't exist
        # cursor.execute("CREATE SEQUENCE clientid START 1;")
        # cursor.execute("CREATE TABLE IF NOT EXISTS clients (client_id INTEGER PRIMARY KEY DEFAULT NEXTVAL('clientid') )")
        # Insert a new client
        cursor.execute("INSERT INTO clients DEFAULT VALUES")
        conn.commit()  # Commit the transaction
        # Get the last inserted client_id
        cursor.execute("SELECT CURRVAL('clientid') AS last_inserted_id;")
        result = cursor.fetchone()
        client_id = result[0] if result else -1
        print(f"Inserted Client ID: {client_id}")
        cursor.close()
        conn.close()
        return client_id
    except duckdb.Error as err:
        print(f"Error: {err}")
        return -1

get_client_tool = FunctionTool(
    func=get_client,
    description="Generates Client ID",
    global_imports=[
        "duckdb",
    ]
)


get_client("ddd")