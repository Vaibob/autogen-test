import asyncio
import re
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.conditions import MaxMessageTermination
from autogen_agentchat.teams import RoundRobinGroupChat
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient
from process_pdf import process_pdf_tool
from read_excel import read_excel_tool
from read_image import read_image_tool
from read_csv import read_csv_tool
from clientid import get_client_tool
from matcher import matcher_tool


async def reconcile_files(clientfiles:list,vendorfiles:list) -> int:
    #gpt-4o-mini is used to perform function calling (allot tools for file type)
    model_client_4o_mini=OpenAIChatCompletionClient(
        model="gpt-4o-mini",
        api_key="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",
        temperature=0
    )

    #starts session with client_id as reference
    session_agent=AssistantAgent(
        name="session_agent",
        description="An agent that starts the session and determines client_id for the session",
        model_client=model_client_4o_mini,
        tools=[get_client_tool],#, update_client_files_tool],
        system_message="""
        You are responsible for determining the client_id for the session.
        1. Use get_client_tool to obtain the client_id.
        2. Distribute the client_id to all other agents.
        3. You will receive a list of client files and a list of vendor files.
        4. For each file, set the identifier to 'client' or 'vendor' based on the input list.
        """
        #5. Use update_client_files_tool to store the client_id, filename, and identifier for each file.
    )

    #picks tools for the file type to read
    reader_agent=AssistantAgent(
        name="reader_agent",
        description="An agent that determines which method to use to read the file",
        model_client=model_client_4o_mini,
        tools=[read_excel_tool,read_csv_tool,read_image_tool,process_pdf_tool],
        system_message="""
        You are responsible for deciding which tool should process each file based on its type.
        1. Wait for the session_agent to provide the client_id.
        2. Receive the client_id from the session_agent.
        3. For each file, determine its type and send the file path, client_id, and identifier ('client'/'vendor') to the appropriate tools:
            - `process_pdf_tool` for PDF files.
            - `read_excel_tool` for Excel files (.xlsx).
            - `read_image_tool` for image files (.png, .jpeg, .jpg).
            - `read_csv_tool` for CSV files.
        Ensure that only the correct files are sent to each tool.
        """
    )
    
    #calls match tool to perform 1:1 matching based on dates and amount.
    matcher_agent=AssistantAgent(
        name="matcher_agent",
        description="uses tool to find matching and non-matching transactions",
        model_client=model_client_4o_mini,
        tools=[matcher_tool],
        system_message="""
        using the client_id, call matcher_tool
        """
    )


    max_messages = MaxMessageTermination(max_messages=4)
    team=RoundRobinGroupChat([session_agent,reader_agent,matcher_agent],termination_condition=max_messages)


    task = f"ClientFiles={clientfiles} and VendorFiles={vendorfiles}"
    result=await Console(team.run_stream(task=task))
    for message in result.messages:
        if hasattr(message, "type") and message.type == "TextMessage":
            text = message.content
        else:
            if isinstance(message.content, list):
                text = " ".join(str(item) for item in message.content)
            else:
                text = str(message.content)
                
        match = re.search(r'client_id[\'"]?:?\s*(\d+)', text)
        if match:
            client_id = int(match.group(1))
  


    return client_id
    

if __name__ == "__main__":
    c_files=[rf"testingDocs\test.pdf"]
    v_files=[rf"testingDocs\auAhmcsv.csv"]
    val=asyncio.run(reconcile_files(c_files,v_files))
    print(val)

