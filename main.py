"""
Customer Support AI Agent — Starter Code
==========================================
Your task is to complete this file by implementing all sections marked
with # TODO comments.

Reference the step-by-step solution files and INSTRUCTIONS.md for guidance.
Do NOT copy the solution directly — work through each section yourself.

Run locally (after filling in config values):
  uv run main.py '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'

Deploy to AgentCore:
  agentcore deploy

Invoke deployed agent:
  agentcore invoke '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'
"""

# ── Imports ───────────────────────────────────────────────────────────────────
# These imports are provided. Do not remove them.
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
import argparse, json, re
import os, asyncio, boto3
from strands.hooks import (
    HookProvider, AfterInvocationEvent, HookRegistry, MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser
from dotenv import load_dotenv


load_dotenv()

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

# ── TODO 1 — App Initialisation ───────────────────────────────────────────────
# Create a BedrockAgentCoreApp instance.
# This registers the ASGI server for AgentCore deployment.
# There must be exactly one instance per deployment.
#
# Hint: app = BedrockAgentCoreApp()

# TODO: Create the BedrockAgentCoreApp instance
app = BedrockAgentCoreApp()


# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"

# ── TODO 2 — Configuration ────────────────────────────────────────────────────
# Replace the placeholder strings with your actual AWS resource values.
# You collected these in Part 1 of the INSTRUCTIONS.
#
# GATEWAY_URL format: https://<alias>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp
# KB_ID       format: 10-character alphanumeric string from the KB console
# REGION:     your AWS region, e.g. "us-east-1"
# MEMORY_ID   format: shown in the AgentCore Memory console

GATEWAY_URL = os.getenv("GATEWAY_URL")   # TODO: Replace with your Gateway URL
KB_ID       = os.getenv("KB_ID")          # TODO: Replace with your Knowledge Base ID
REGION      = os.getenv("AWS_REGION", "us-east-1")        # TODO: Replace with your AWS region
MEMORY_ID   = os.getenv("MEMORY_ID")        # TODO: Replace with your Memory ID


# ── TODO 3 — Model and Clients ────────────────────────────────────────────────
# Create:
#   1. A BedrockModel using model_id "global.amazon.nova-2-lite-v1:0"
#   2. A MemoryClient with region_name=REGION
#   3. A boto3 client for the "bedrock-agent-runtime" service in REGION
#
# Hint: model = BedrockModel(model_id=model_id)

model_id = "global.amazon.nova-2-lite-v1:0"

# TODO: Create the BedrockModel instance
model = BedrockModel(model_id=model_id, region_name=REGION)

# TODO: Create the MemoryClient instance
memory_client = MemoryClient(region_name=REGION)

# TODO: Create the boto3 bedrock-agent-runtime client
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)


# ── TODO 4 — Namespace Helper ─────────────────────────────────────────────────
# Implement get_namespaces() to return a dict mapping strategy type to
# namespace template string.
#
# Steps:
#   1. Call mem_client.get_memory_strategies(memory_id) to get strategy list
#   2. Return a dict: { strategy["type"]: strategy["namespaces"][0] for each strategy }
#
# Example output:
#   { "SEMANTIC": "cs_agent/{actorId}/facts",
#     "USER_PREFERENCE": "cs_agent/{actorId}/preferences" }

def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """Return a dict mapping strategy type → namespace template string."""
    strategies = mem_client.get_memory_strategies(memory_id)
    return {s["type"]: s["namespaces"][0] for s in strategies}


# ── TODO 5 — Memory Hook ──────────────────────────────────────────────────────
# Implement MemoryHook, a HookProvider subclass that adds long-term memory.
#
# The class needs:
#   __init__(self, actor_id, session_id, memory_client, memory_id)
#     — store all four as instance attributes
#     — call get_namespaces() and store the result as self.namespaces
#
#   retrieve_customer_context(self, event: MessageAddedEvent)
#     — only runs for plain-text user messages (not tool results)
#     — for each strategy namespace, call memory_client.retrieve_memories(
#          memory_id, namespace (formatted with actorId), query, top_k=5)
#     — collect non-empty memory texts tagged with their strategy type
#     — if any memories found, prepend them to the user message as:
#          "Customer Context:\n<memories>\n\n<original_message>"
#
#   save_support_interaction(self, event: AfterInvocationEvent)
#     — walk the message list backwards to find the last plain-text user
#       query and the last assistant response
#     — call memory_client.create_event(memory_id, actor_id, session_id,
#          messages=[(customer_query, "USER"), (agent_response, "ASSISTANT")])
#
#   register_hooks(self, registry: HookRegistry)
#     — register retrieve_customer_context on MessageAddedEvent
#     — register save_support_interaction on AfterInvocationEvent

class MemoryHook(HookProvider):
    """Long-term memory hook for the customer support agent."""

    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        self.actor_id = actor_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = get_namespaces(memory_client, memory_id)

    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        messages = event.agent.messages
        if not messages:
            return

        last_message = messages[-1]
        if last_message.get("role") != "user":
            return

        content = last_message.get("content", [])
        if not content or "text" not in content[0]:
            # Skip tool results and other non-plain-text content
            return

        user_query = content[0]["text"]
        if not user_query:
            return

        collected_context = []
        for strategy_type, namespace_template in self.namespaces.items():
            resolved_namespace = namespace_template.format(actorId=self.actor_id)
            try:
                memories = self.memory_client.retrieve_memories(
                    memory_id=self.memory_id,
                    namespace=resolved_namespace,
                    query=user_query,
                    top_k=5,
                )
            except Exception as exc:
                logger.warning("Memory retrieval failed for %s: %s", strategy_type, exc)
                continue

            for memory in memories:
                text = memory.get("content", {}).get("text", "").strip()
                if text:
                    collected_context.append(f"[{strategy_type}] {text}")

        if collected_context:
            context_block = "\n".join(collected_context)
            content[0]["text"] = f"Customer Context:\n{context_block}\n\n{user_query}"

    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
        messages = event.agent.messages
        customer_query = None
        agent_response = None

        for message in reversed(messages):
            content = message.get("content", [])
            if not content or "text" not in content[0]:
                continue
            text = content[0]["text"]
            role = message.get("role")
            if role == "assistant" and agent_response is None:
                agent_response = text
            elif role == "user" and customer_query is None:
                customer_query = text
            if customer_query and agent_response:
                break

        if not (customer_query and agent_response):
            return

        try:
            self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[(customer_query, "USER"), (agent_response, "ASSISTANT")],
            )
        except Exception as exc:
            logger.warning("Failed to save support interaction to memory: %s", exc)

    def register_hooks(self, registry: HookRegistry) -> None:  # type: ignore
        """Register both memory callbacks."""
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)

# ── TODO 6 — Knowledge Base Tool ─────────────────────────────────────────────
# Implement search_knowledge_base(query) using the @tool decorator.
#
# Steps:
#   1. Guard: if KB_ID is empty return "Knowledge base not configured."
#   2. Call _bedrock_runtime.retrieve(
#          knowledgeBaseId=KB_ID,
#          retrievalQuery={"text": query}
#      )
#   3. Extract resp["retrievalResults"]; return a message if empty
#   4. Join the text chunks with "\n---\n" and return the result
#
# The docstring is the tool description — the model uses it to decide when
# to call this tool, so keep it clear and accurate.

@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    # TODO: Implement the Knowledge Base search

    if not KB_ID:
        return "Knowledge base not configured."

    try:
        response = _bedrock_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": query},
        )
    except Exception as exc:
        logger.error("Knowledge base retrieval failed: %s", exc)
        return f"Knowledge base search failed: {exc}"

    results = response.get("retrievalResults", [])
    if not results:
        return "No relevant information found in the knowledge base."

    chunks = [r["content"]["text"] for r in results if r.get("content", {}).get("text")]
    return "\n---\n".join(chunks)


# ── TODO 7 — Loyalty Discount Tool (Code Interpreter) ────────────────────────
# Implement calculate_loyalty_discount() using the @tool decorator.
#
# The tool must:
#   1. Build a self-contained Python code string that:
#        • Defines earn_rates: {"standard": 1, "device": 2, "fresh": 5}
#        • Defines tier_rates: {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
#        • Calculates points_redeemed (floor to nearest 500, cap at 50% of order)
#        • Calculates tier_discount (applied to subtotal after points)
#        • Calculates final_total, total_savings, points_earned, remaining_points
#        • Prints a JSON result dict
#   2. Execute the code with code_session(REGION).invoke("executeCode", {...})
#      using language="python" and clearContext=True
#   3. Return the first result event as a JSON string
#   4. Include a fallback that computes only the tier discount if the
#      Code Interpreter is unavailable

@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Exact order total in USD from the customer message.
                          Never invent or default this (do not use 100 unless
                          the customer stated 100).
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price
    """
    # TODO: Build the code string (use an f-string to inject the arguments)
    code = code = f"""
    import json

    earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
    tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

    loyalty_points = {loyalty_points}
    tier = "{tier}"
    order_total = {order_total}
    product_category = "{product_category}"

    # Redeem points in blocks of 500, capped at 50% of the order total
    candidate_points = (loyalty_points // 500) * 500
    candidate_value = candidate_points * 0.01
    cap_value = order_total * 0.5

    if candidate_value > cap_value:
        max_points_by_cap = int(cap_value / 0.01)
        points_redeemed = (max_points_by_cap // 500) * 500
    else:
        points_redeemed = candidate_points

    points_value = points_redeemed * 0.01
    subtotal_after_points = order_total - points_value

    tier_discount_rate = tier_rates.get(tier, 0.00)
    tier_discount = subtotal_after_points * tier_discount_rate

    final_total = subtotal_after_points - tier_discount
    total_savings = order_total - final_total

    earn_rate = earn_rates.get(product_category, 1)
    points_earned = int(final_total * earn_rate)
    remaining_points = loyalty_points - points_redeemed + points_earned

    result = {{
        "order_total": round(order_total, 2),
        "tier": tier,
        "points_redeemed": points_redeemed,
        "points_value": round(points_value, 2),
        "tier_discount_rate": tier_discount_rate,
        "tier_discount": round(tier_discount, 2),
        "final_total": round(final_total, 2),
        "total_savings": round(total_savings, 2),
        "points_earned": points_earned,
        "remaining_points": remaining_points,
    }}

    print(json.dumps(result))
    """

    try:
        with code_session(REGION) as code_client:
            response = code_client.invoke(
                "executeCode",
                {"code": code, "language": "python", "clearContext": True},
            )
            for event in response["stream"]:
                if "result" in event:
                    for content_item in event["result"].get("content", []):
                        if content_item.get("type") == "text":
                            return content_item["text"]
            return json.dumps({"error": "No result returned from Code Interpreter"})

    except Exception as e:
        logger.warning("Code Interpreter unavailable, using fallback: %s", e)
        tier_rates = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        tier_discount_rate = tier_rates.get(tier, 0.00)
        tier_discount = order_total * tier_discount_rate
        final_total = order_total - tier_discount
        return json.dumps({
            "order_total": round(order_total, 2),
            "tier": tier,
            "tier_discount_rate": tier_discount_rate,
            "tier_discount": round(tier_discount, 2),
            "final_total": round(final_total, 2),
            "note": "Fallback calculation — Code Interpreter unavailable, points redemption not applied.",
        })


def _extract_stated_order_total(text: str) -> float | None:
    """Pull an explicit USD order amount from the customer message."""
    if not text:
        return None
    patterns = (
        r"\$\s*(\d+(?:\.\d{1,2})?)",
        r"(\d+(?:\.\d{1,2})?)\s*(?:USD|usd|dollars?)",
        r"(?:order(?:\s+total)?)\s+(?:of\s+)?(?:a\s+)?(\d+(?:\.\d{1,2})?)",
        r"(\d+(?:\.\d{1,2})?)\s+(?:standard|device|fresh)\s+order",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if not match:
            continue
        value = float(match.group(1))
        if 0 < value < 10_000:
            return value
    return None


# ── TODO 8 — Agent Entrypoint ─────────────────────────────────────────────────
# Implement the invoke() function decorated with @app.entrypoint.
#
# Steps:
#   1. Extract user_input, actor_id, and session_id from the payload
#      (generate a UUID if session_id is missing)
#   2. Instantiate MemoryHook for this actor/session
#   3. Instantiate AgentCoreBrowser(region=REGION)
#   4. Build the tools list: [search_knowledge_base, calculate_loyalty_discount,
#                              agent_core_browser.browser]
#   5. Connect to the Gateway via MCPClient, load gateway_tools, extend tools list
#   6. Create and invoke the Agent with all tools, hooks, and system_prompt
#   7. Return the text from the first content block of the response
#   8. Handle exceptions gracefully

@app.entrypoint
def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.

    Expected payload keys:
      prompt      (str, required) — the customer's message
      customer_id (str, optional) — unique customer identifier
      session_id  (str, optional) — session identifier; generated if absent
    """
    user_input = payload.get("prompt", "")
    actor_id = payload.get("customer_id", "anonymous")
    session_id = payload.get("session_id") or str(uuid.uuid4())
    stated_total = _extract_stated_order_total(user_input)
    if stated_total is not None:
        user_input = (
            f"{user_input}\n\n"
            "[System] Use calculate_loyalty_discount with these exact values "
            f"from the customer message: order_total={stated_total}. "
            "Do not substitute a default such as 100."
        )

    memory_hook = MemoryHook(
        actor_id=actor_id,
        session_id=session_id,
        memory_client=memory_client,
        memory_id=MEMORY_ID,
    )

    agent_core_browser = AgentCoreBrowser(region=REGION)

    tools = [search_knowledge_base, calculate_loyalty_discount, agent_core_browser.browser]

    gateway_client = MCPClient(lambda: aws_iam_streamablehttp_client(
        endpoint=GATEWAY_URL,
        aws_region=REGION,
        aws_service="bedrock-agentcore",
    ))

    system_prompt = (
        "You are a helpful customer support assistant for an e-commerce platform. "
        "You can track orders, process refunds, answer product and policy questions "
        "using the knowledge base, calculate loyalty discounts, and browse the web "
        "when needed. For any request containing a URL or asking you to visit a "
        "website, you MUST use the browser tool. Initialize a browser session, "
        "navigate to the requested URL, and use a browser action such as evaluate "
        "with document.title when the page title is requested. Report the exact "
        "tool result. Never claim that browsing is unavailable unless the browser "
        "tool returned an error. Always use the available tools to get real data — "
        "never fabricate order numbers, refund IDs, tracking numbers, or any other "
        "identifiers. When calculating a loyalty discount, copy loyalty_points, "
        "tier, and order_total exactly from the customer message; never assume "
        "an order total of 100 unless the customer stated 100. Be concise, "
        "accurate, and polite."
    )

    try:
        with gateway_client:
            gateway_tools = gateway_client.list_tools_sync()
            tools.extend(gateway_tools)

            agent = Agent(
                model=model,
                tools=tools,
                hooks=[memory_hook],
                system_prompt=system_prompt,
            )

            response = agent(user_input)
            return response.message["content"][0]["text"]

    except Exception as e:
        logger.error("Agent invocation failed: %s", e)
        return f"I'm sorry, something went wrong while processing your request: {e}"

# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = invoke(json.loads(args.payload))
    print(response)


if __name__ == "__main__":
    app.run()
    # Uncomment the line below and comment app.run() for local CLI testing:
    # main()
