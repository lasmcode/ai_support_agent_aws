# AI Customer Support Agent (Amazon Bedrock AgentCore & Strands SDK)

A multi-tool, conversational AI customer support assistant built with the **Strands SDK** and **Amazon Bedrock AgentCore**. This agent acts as an intelligent interface for an e-commerce platform, handling complex multi-turn conversations, order tracking, returns processing, RAG-based product catalog lookup, cross-session customer memory, loyalty calculation, and live web browsing.

---

## 🌟 Key Features

* **Order Tracking & Management:** Integrates with backend Lambda microservices via AgentCore Gateway using Model Context Protocol (MCP) and API Gateway REST proxies.
* **Returns & Refund Processing:** Handles return label generation and refund initiation using direct Lambda integrations.
* **Knowledge Base Retrieval (RAG):** Answers customer policy, shipping, and product catalog queries using Amazon Bedrock Knowledge Bases (powered by Amazon Titan Embeddings v2 and OpenSearch Serverless).
* **Cross-Session Persistent Memory:** Retains customer preferences, facts, and conversation context across separate sessions using AgentCore Memory strategies (`customer_facts` and `customer_preferences`).
* **Code Execution Sandbox:** Runs exact mathematical computations for loyalty point redemptions and tier discount calculations using AgentCore Code Interpreter.
* **Web Browsing:** Interacts with live web content using AgentCore Browser Tool to fetch real-time external information.
