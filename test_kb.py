from dotenv import load_dotenv
load_dotenv()
from main import search_knowledge_base

result = search_knowledge_base("What are the benefits of the Platinum loyalty tier?")
print(result)