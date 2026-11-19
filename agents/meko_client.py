"""Thin client for the Meko MCP server.

Every Meko tool call made through this client carries the datapack ID, the
agent ID and (once set) the conversation ID, so Meko nests the call inside
the trace for the decision being made.
"""

import json
import os
from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

MEKO_URL = os.environ.get("MEKO_MCP_URL", "https://mcp.mekodata.ai/mcp")


class MekoError(RuntimeError):
    """A Meko tool call failed or returned an error payload."""


class Meko:
    def __init__(self, session, datapack_id, agent_id):
        self.session = session
        self.datapack_id = datapack_id
        self.agent_id = agent_id

    async def call(self, tool, **arguments):
        """Call one Meko tool and return its parsed JSON result."""
        arguments = {k: v for k, v in arguments.items() if v is not None}
        result = await self.session.call_tool(tool, arguments)
        text = "".join(
            block.text for block in result.content
            if getattr(block, "type", "") == "text"
        )
        if result.is_error:
            raise MekoError(f"{tool} failed: {text}")
        try:
            data = json.loads(text)
        except ValueError:
            return text
        if isinstance(data, dict) and data.get("error"):
            raise MekoError(f"{tool} returned an error: {text}")
        return data

    async def start_conversation(self, title, metadata=None):
        data = await self.call(
            "conversation_create",
            agent_id=self.agent_id,
            datapack_id=self.datapack_id,
            title=title,
            metadata=json.dumps(metadata) if metadata else None,
        )
        return data["id"]

    async def search_knowledge(self, conversation_id, query, limit=4):
        data = await self.call(
            "knowledgebase_search",
            query=query,
            conversation_id=conversation_id,
            datapack_id=self.datapack_id,
            agent_id=self.agent_id,
            limit=limit,
        )
        return data.get("results", []) if isinstance(data, dict) else []

    async def search_memory(self, conversation_id, query, limit=10):
        data = await self.call(
            "memory_search",
            query=query,
            conversation_id=conversation_id,
            datapack_id=self.datapack_id,
            agent_id=self.agent_id,
            limit=limit,
        )
        return data.get("results", []) if isinstance(data, dict) else []

    async def add_memory(self, conversation_id, text, metadata=None):
        return await self.call(
            "memory_add",
            text=text,
            conversation_id=conversation_id,
            datapack_id=self.datapack_id,
            agent_id=self.agent_id,
            metadata=json.dumps(metadata) if metadata else None,
        )

    async def add_message(self, conversation_id, input_text, output_text,
                          reasoning=None, plan=None, metadata=None):
        return await self.call(
            "conversation_add_message",
            conversation_id=conversation_id,
            datapack_id=self.datapack_id,
            agent_id=self.agent_id,
            input=input_text,
            output=output_text,
            reasoning=reasoning,
            plan=plan,
            metadata=json.dumps(metadata) if metadata else None,
        )

    async def track_tokens(self, conversation_id, model, input_tokens,
                           output_tokens, message_id=None):
        return await self.call(
            "track_token_usage",
            conversation_id=conversation_id,
            datapack_id=self.datapack_id,
            name="LLM Response",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            message_id=message_id,
        )


@asynccontextmanager
async def connect(api_key, datapack_id, agent_id):
    """Open an MCP session with Meko, authenticated by API key."""
    headers = {"Authorization": f"Bearer {api_key}"}
    async with create_mcp_http_client(headers=headers) as http_client:
        async with streamable_http_client(MEKO_URL, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield Meko(session, datapack_id, agent_id)
