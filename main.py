"""
main.py — InfraGuard AI uAgent with Agent Chat Protocol

A Fetch.ai uAgent that uses the official Agent Chat Protocol (ACP v0.3.0)
to handle natural-language infrastructure resilience queries.

Uses the shared InfraGuard simulation engine for all logic.

Run:  venv\\Scripts\\python.exe main.py

Environment variables (in .env):
  INFRAGUARD_SEED    — stable seed phrase for agent identity (required)
  INFRAGUARD_PORT    — local port (default: 8001)
"""

import os
import sys
import asyncio
import logging
from uuid import uuid4
from datetime import datetime, timezone

from dotenv import load_dotenv

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatMessage,
    ChatAcknowledgement,
    TextContent,
    chat_protocol_spec,
)

from infraguard.simulation import InfraGuardSimulation
from infraguard.commands import parse_and_execute

# ──────────────────────────────────────────────────────────────
# Load config
# ──────────────────────────────────────────────────────────────
load_dotenv()

SEED = os.getenv("INFRAGUARD_SEED", "infraguard-ai-resilience-agent-seed-v1")
PORT = int(os.getenv("INFRAGUARD_PORT", "8001"))

# ──────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("infraguard")

# ──────────────────────────────────────────────────────────────
# Simulation engine (shared singleton for this agent process)
# ──────────────────────────────────────────────────────────────
sim = InfraGuardSimulation()

# ──────────────────────────────────────────────────────────────
# Create agent
# ──────────────────────────────────────────────────────────────
agent = Agent(
    name="InfraGuard",
    seed=SEED,
    port=PORT,
    mailbox=True,
    handle_messages_concurrently=True,
)

logger.info(f"InfraGuard Agent address: {agent.address}")

# ──────────────────────────────────────────────────────────────
# Chat Protocol — ACP v0.3.0
# ──────────────────────────────────────────────────────────────
chat_proto = Protocol(spec=chat_protocol_spec)


@chat_proto.on_message(ChatMessage)
async def handle_chat_message(ctx: Context, sender: str, msg: ChatMessage):
    """Handle incoming Agent Chat Protocol messages with minimal latency."""
    # 1. Fire-and-forget ACK concurrently so it doesn't block the actual reply
    ack = ChatAcknowledgement(
        acknowledged_msg_id=msg.msg_id,
        metadata={"status": "processing"},
    )
    asyncio.create_task(ctx.send(sender, ack))
    logger.info(f"Received ChatMessage from {sender}: msg_id={msg.msg_id}")

    # 2. Extract text content
    user_text = msg.text()
    if not user_text.strip():
        user_text = "help"

    logger.info(f"Query: {user_text[:200]}")

    # 3. Execute against the simulation engine
    try:
        response_text = parse_and_execute(sim, user_text)
    except Exception as e:
        logger.error(f"Simulation error: {e}", exc_info=True)
        response_text = f"An error occurred while processing your request: {str(e)}"

    logger.info(f"Response length: {len(response_text)} chars")

    # 4. Send the response as a ChatMessage
    response_msg = ChatMessage(
        content=[TextContent(text=response_text)],
    )
    await ctx.send(sender, response_msg)
    logger.info(f"Sent response to {sender}")


@chat_proto.on_message(ChatAcknowledgement)
async def handle_chat_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    """Handle incoming acknowledgements (no action needed)."""
    logger.info(f"Received ACK from {sender} for msg_id={msg.acknowledged_msg_id}")


agent.include(chat_proto, publish_manifest=True)

# ──────────────────────────────────────────────────────────────
# Startup event
# ──────────────────────────────────────────────────────────────
@agent.on_event("startup")
async def on_startup(ctx: Context):
    logger.info("=" * 60)
    logger.info("InfraGuard AI Agent — Starting up")
    logger.info(f"  Agent name:    InfraGuard")
    logger.info(f"  Agent address: {agent.address}")
    logger.info(f"  Port:          {PORT}")
    logger.info(f"  Protocol:      {chat_protocol_spec.name} v{chat_protocol_spec.version}")
    logger.info("=" * 60)
    logger.info("")
    logger.info("Supported commands:")
    logger.info("  - 'What happens if [component] fails?'")
    logger.info("  - 'Activate Backup Generator'")
    logger.info("  - 'Check route from [A] to [B]'")
    logger.info("  - 'Which critical services are affected?'")
    logger.info("  - 'Recover [component]'")
    logger.info("  - 'Status'")
    logger.info("  - 'Reset'")
    logger.info("  - 'Help'")
    logger.info("")
    logger.info("Waiting for Agent Chat Protocol messages...")


# ──────────────────────────────────────────────────────────────
# Run
# ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    agent.run()
