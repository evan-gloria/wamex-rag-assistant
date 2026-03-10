import os
import json
import boto3
import logging
from langchain_aws import BedrockEmbeddings, ChatBedrock
from langchain_community.vectorstores import FAISS
from langchain.chains import create_retrieval_chain
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate

# Set up enterprise logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
bedrock_client = boto3.client('bedrock-runtime')

# Environment Variables
BUCKET_NAME = os.environ.get('S3_BUCKET_NAME')

# Initialize Bedrock Models
# We use Titan for embeddings (to match the ingestion phase) and Claude 4.5 Haiku for fast, cheap generation
embeddings = BedrockEmbeddings(client=bedrock_client, model_id="amazon.titan-embed-text-v2:0")
llm = ChatBedrock(client=bedrock_client, model_id="anthropic.claude-haiku-4-5-20251001-v1:0")

def download_index_from_s3():
    """Helper function to pull the FAISS vectors from S3 to ephemeral storage"""
    local_path = "/tmp/index"
    os.makedirs(local_path, exist_ok=True)
    
    faiss_file = f"{local_path}/index.faiss"
    pkl_file = f"{local_path}/index.pkl"
    
    # Check if this is a warm start. If files exist, skip the download!
    if os.path.exists(faiss_file) and os.path.exists(pkl_file):
        logger.info("Warm start detected! FAISS index already in /tmp/. Skipping S3 download.")
        return local_path
        
    try:
        logger.info(f"Downloading FAISS index from {BUCKET_NAME}...")
        s3_client.download_file(BUCKET_NAME, "index/index.faiss", faiss_file)
        s3_client.download_file(BUCKET_NAME, "index/index.pkl", pkl_file)
        return local_path
    except Exception as e:
        logger.error(f"Error downloading index from S3: {str(e)}")
        return None

def lambda_handler(event, context):
    # 1. Parse the incoming API Gateway request
    try:
        body = json.loads(event.get('body', '{}'))
        user_question = body.get('question', '')
        selected_sources = body.get('selected_files', [])
    except Exception:
        return {"statusCode": 400, "body": json.dumps("Invalid request payload. Expected JSON.")}

    if not user_question:
        return {"statusCode": 400, "body": json.dumps("Please provide a 'question' in the request body.")}

    logger.info(f"Received question: {user_question}")

    # 2. Pull the vector database into memory
    local_index_path = download_index_from_s3()
    if not local_index_path:
        return {"statusCode": 500, "body": json.dumps("Internal Server Error: Could not load vector index.")}

    # Load FAISS (allow_dangerous_deserialization is required for trusted local pickle files in newer LangChain versions)
    vectorstore = FAISS.load_local(local_index_path, embeddings, allow_dangerous_deserialization=True)
    
    # Configure the retriever to pull the top 4 most relevant geological chunks
    search_kwargs = {"k": 20}
    if selected_sources:
        search_kwargs["filter"] = lambda metadata: metadata.get("source") in selected_sources

    retriever = vectorstore.as_retriever(search_kwargs=search_kwargs)

    # 3. Construct the RAG Prompt
    system_prompt = (
        "You are an expert geological data assistant. Use the following context retrieved from WAMEX reports "
        "to answer the user's question. If you do not know the answer based strictly on the context, "
        "say 'I cannot answer this based on the provided WAMEX reports.' Do not hallucinate.\n\n"
        "Context:\n{context}"
    )
    
    prompt = ChatPromptTemplate.from_messages([
        ("system", system_prompt),
        ("human", "{input}")
    ])
    
    # 4. Chain it all together and execute
    question_answer_chain = create_stuff_documents_chain(llm, prompt)
    rag_chain = create_retrieval_chain(retriever, question_answer_chain)
    
    logger.info("Querying LLM with retrieved context...")
    response = rag_chain.invoke({"input": user_question})

    # Extract unique source PDFs to prove to the user where the data came from
    sources = list(set([doc.metadata.get('source', 'Unknown') for doc in response["context"]]))

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "answer": response["answer"],
            "sources": sources
        })
    }