"""
Create a Managed Agent: Coding Assistant

This script creates a persistent Managed Agent via the Anthropic API.
Run once, then store the returned agent ID for use in sessions.

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    python create_agent.py
"""

import anthropic


def create_coding_assistant():
    client = anthropic.Anthropic()

    agent = client.beta.agents.create(
        name="Coding Assistant",
        model="claude-sonnet-4-6",
        tools=[
            {
                "type": "agent_toolset_20260401",
                "configs": [
                    {"name": "web_fetch", "enabled": False},
                ],
            }
        ],
    )

    print(f"Agent created successfully!")
    print(f"  ID:      {agent.id}")
    print(f"  Name:    {agent.name}")
    print(f"  Version: {agent.version}")
    print()
    print("Save the agent ID for use in sessions:")
    print(f'  AGENT_ID="{agent.id}"')

    return agent


if __name__ == "__main__":
    create_coding_assistant()
