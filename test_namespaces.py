from dotenv import load_dotenv
load_dotenv()
import os
from bedrock_agentcore.memory import MemoryClient
from main import get_namespaces

client = MemoryClient(region_name=os.getenv("AWS_REGION", "us-east-1"))
result = get_namespaces(client, os.getenv("MEMORY_ID"))
print(result)