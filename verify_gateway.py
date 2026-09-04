"""Verifica que la AgentCore Gateway expone las 6 herramientas esperadas desde .env."""
import asyncio
import os
from dotenv import load_dotenv
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from mcp.client.session import ClientSession

load_dotenv()


GATEWAY_URL = os.getenv("GATEWAY_URL")
REGION = os.getenv("AWS_REGION", "us-east-1")


async def main() -> None:
    async with aws_iam_streamablehttp_client(
        endpoint=GATEWAY_URL,
        aws_region=REGION,
        aws_service="bedrock-agentcore",
    ) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            all_tools = []
            cursor = None
            while True:
                result = await session.list_tools(cursor=cursor)
                all_tools.extend(result.tools)
                cursor = getattr(result, "nextCursor", None)
                if not cursor:
                    break

            print(f"\n✅ {len(all_tools)} herramientas encontradas en la Gateway:\n")
            for tool in all_tools:
                print(f"  - {tool.name}: {tool.description}")


if __name__ == "__main__":
    asyncio.run(main())