import os
import json
import boto3
import logging
from urllib.parse import unquote_plus
from langchain_community.document_loaders import PyPDFLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_aws import BedrockEmbeddings
from langchain_community.vectorstores import FAISS

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client('s3')
bedrock_client = boto3.client('bedrock-runtime')

embeddings = BedrockEmbeddings(
    client=bedrock_client,
    model_id="amazon.titan-embed-text-v2:0" 
)

def lambda_handler(event, context):
    # 1. Loop through SQS messages (batching)
    for sqs_record in event['Records']:
        
        # 2. Parse the stringified S3 event inside the SQS body
        s3_event = json.loads(sqs_record['body'])
        
        # (Optional but recommended) S3 sends a test event when first configured
        if 'Event' in s3_event and s3_event['Event'] == 's3:TestEvent':
            continue
            
        # 3. Loop through the actual S3 records
        if 'Records' in s3_event:
            for s3_record in s3_event['Records']:
                bucket_name = s3_record['s3']['bucket']['name']
                object_key = unquote_plus(s3_record['s3']['object']['key'])
                
                # ---> INSERT YOUR EXISTING FAISS/BEDROCK LOGIC HERE <---
                # Allow both PDF and TXT. Ignore the 'index/' folder to prevent loops.
                if object_key.startswith('index/') or not (object_key.lower().endswith('.pdf') or object_key.lower().endswith('.txt')):
                    logger.info(f"Skipping file: {object_key}")
                    continue
                
                try:
                    local_file_path = f"/tmp/{os.path.basename(object_key)}"
                    s3_client.download_file(bucket_name, object_key, local_file_path)
                    
                    # 1. Branching Loader based on file type
                    if object_key.lower().endswith('.pdf'):
                        loader = PyPDFLoader(local_file_path)
                    else:
                        loader = TextLoader(local_file_path)
                        
                    documents = loader.load()
                    
                    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=150)
                    docs = text_splitter.split_documents(documents)
                    for doc in docs:
                        doc.metadata['source'] = object_key
                    
                    # 2. Generate a temporary index for the NEW document
                    new_vectorstore = FAISS.from_documents(documents=docs, embedding=embeddings)
                    
                    # 3. THE MERGE LOGIC: Download and load the EXISTING index from S3
                    local_index_dir = "/tmp/faiss_index"
                    os.makedirs(local_index_dir, exist_ok=True)
                    
                    try:
                        # Attempt to download existing index files
                        s3_client.download_file(bucket_name, "index/index.faiss", f"{local_index_dir}/index.faiss")
                        s3_client.download_file(bucket_name, "index/index.pkl", f"{local_index_dir}/index.pkl")
                        
                        # Load existing index and merge new one into it
                        existing_vectorstore = FAISS.load_local(
                            local_index_dir, 
                            embeddings, 
                            allow_dangerous_deserialization=True
                        )
                        existing_vectorstore.merge_from(new_vectorstore)
                        existing_vectorstore.save_local(local_index_dir)
                        logger.info("Successfully merged new data into existing FAISS index.")
                        
                    except Exception as e:
                        # If download fails (e.g., first file ever), current becomes the index
                        logger.info("No existing index found or error loading. Starting fresh index.")
                        new_vectorstore.save_local(local_index_dir)

                    # 4. Upload the combined index back to S3
                    s3_client.upload_file(f"{local_index_dir}/index.faiss", bucket_name, "index/index.faiss")
                    s3_client.upload_file(f"{local_index_dir}/index.pkl", bucket_name, "index/index.pkl")
                    
                    logger.info(f"Processing {object_key} from {bucket_name}")
                    
                except Exception as e:
                    logger.error(f"Error processing {object_key}: {str(e)}")
                    raise e    
    return {"statusCode": 200, "body": json.dumps("Ingestion complete")}