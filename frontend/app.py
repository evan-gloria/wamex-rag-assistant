import streamlit as st
import requests
import boto3
import os
from dotenv import load_dotenv

# Load variables from the .env file
load_dotenv()

# Your live AWS API Gateway Endpoint
API_URL = os.getenv("API_URL")
BUCKET_NAME = os.getenv("S3_BUCKET_NAME")
PROFILE_NAME = os.getenv("AWS_PROFILE")


# Initialize S3 client for the sidebar
# Create a session using your specific AWS profile
session = boto3.Session(profile_name=PROFILE_NAME) # Change 'default' to your actual profile name if different
s3 = session.client('s3', region_name='ap-southeast-2')


# Configure the Streamlit page
st.set_page_config(page_title="WAMEX RAG Assistant", page_icon="⛏️")
st.title("WAMEX Geological Assistant")
st.markdown("Ask natural language questions about your serverless geological vector database.")

# Initialize the chat history in the browser's session state
if "messages" not in st.session_state:
    st.session_state.messages = []

# Redraw previous chat messages whenever the app rerenders
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# --- UI SIDEBAR: List Available Sources ---
selected_files = [] # Array to hold the ticked files

if "available_files" not in st.session_state:
    st.session_state.available_files = []

def select_all():
    for f in st.session_state.available_files:
        st.session_state[f] = True

def deselect_all():
    for f in st.session_state.available_files:
        st.session_state[f] = False

with st.sidebar:
    st.header("📚 Available WAMEX Reports")
    try:
        response = s3.list_objects_v2(Bucket=BUCKET_NAME)
        if 'Contents' in response:
            # Safely filter for only PDFs, ignoring the index folder
            files = [obj['Key'] for obj in response['Contents'] 
                     if not obj['Key'].startswith('index/') and obj['Key'].lower().endswith('.pdf')]
            
            # Store the current file list in memory for the buttons to use
            st.session_state.available_files = files
            
            # 1. The Select / Deselect Buttons side-by-side
            col1, col2 = st.columns(2)
            with col1:
                st.button("Select All", on_click=select_all)
            with col2:
                st.button("Clear All", on_click=deselect_all)
            
            st.markdown("Select files to include in search:")
            
            # 2. The Scrollable Container (250 pixels high)
            with st.container(height=250):
                for f in files:
                    # Ensure every file has a default state (True) on first load
                    if f not in st.session_state:
                        st.session_state[f] = True
                    
                    # Tie the checkbox directly to the session state using the 'key' argument
                    st.checkbox(f, key=f)
            
            # 3. Gather the currently checked files to send to the API
            selected_files = [f for f in files if st.session_state[f]]
            
            st.caption(f"{len(selected_files)} / {len(files)} documents selected")
            
        else:
            st.info("No documents found in S3.")
            selected_files = [] # Fallback
            
    except Exception as e:
        st.error(f"S3 Error: {str(e)}")
        selected_files = [] # Fallback

    # --- ADD THIS FOOTER ---
    st.markdown("---") # Adds a subtle visual divider
    st.markdown("### 🌍 Data Provenance")
    st.info(
        "These unstructured geological reports were publicly sourced from the "
        "[Western Australia DMIRS Data and Software Centre (DASC)]"
        "(https://dasc.dmirs.wa.gov.au)."
        
    )
    st.caption("*This application is a proof-of-concept built strictly for personal portfolio and educational purposes. It is not affiliated with or endorsed by the WA Government.*")
    # Your personal signature at the very bottom
    st.caption("⚙️ Engineered by Evan G.")
        
# The chat input box at the bottom of the screen
if prompt := st.chat_input("E.g., What are the lithium assay results at Bungarra?"):
    
    # 1. Save and display the user's question
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 2. Call the AWS API Gateway backend
    with st.chat_message("assistant"):
        with st.spinner("Searching FAISS index and querying Claude 3 Haiku..."):
            try:
                # ADD selected_files to the payload sent to AWS
                # Send the POST request to your cloud architecture
                payload = {
                    "question": prompt,
                    "selected_files": selected_files
                }
                response = requests.post(API_URL, json=payload)
                response.raise_for_status()
                data = response.json()
                
                # Parse the JSON response
                answer = data.get("answer", "No answer received.")
                sources = data.get("sources", [])
                
                # Display the generated answer
                st.markdown(answer)
                
                # Display the provenance/sources as a small caption
                if sources:
                    st.caption(f"**Grounded Sources:** {', '.join(sources)}")
                    
                # Save the assistant's response to the chat history
                st.session_state.messages.append({"role": "assistant", "content": answer})
                
            except Exception as e:
                st.error(f"Error connecting to cloud backend: {str(e)}")

