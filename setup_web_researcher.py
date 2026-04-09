"""
Setup: Web Researcher Agent (run once)

Creates the environment and agent. Save the printed IDs to .env or config.

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    python setup_web_researcher.py
"""

import json
import anthropic


def setup():
    client = anthropic.Anthropic()

    # 1. Create environment (reusable across sessions)
    environment = client.beta.environments.create(
        name="web-researcher-env",
        config={
            "type": "cloud",
            "networking": {"type": "unrestricted"},
        },
    )
    print(f"Environment created: {environment.id}")

    # 2. Create agent with web_search + web_fetch enabled
    agent = client.beta.agents.create(
        name="Web Researcher",
        model="claude-sonnet-4-6",
        system=(
            "Você é um agente de pesquisa na web. "
            "Quando o usuário pedir uma pesquisa, use web_search para buscar informações "
            "e web_fetch para acessar páginas relevantes. "
            "Apresente os resultados de forma organizada em português, "
            "com fontes e links. Seja objetivo e completo."
        ),
        tools=[
            {
                "type": "agent_toolset_20260401",
                "default_config": {"enabled": False},
                "configs": [
                    {"name": "web_search", "enabled": True},
                    {"name": "web_fetch", "enabled": True},
                    {"name": "read", "enabled": True},
                    {"name": "write", "enabled": True},
                ],
            }
        ],
    )
    print(f"Agent created:      {agent.id} (version {agent.version})")

    # Save IDs to config file
    config = {
        "agent_id": agent.id,
        "agent_version": agent.version,
        "environment_id": environment.id,
    }
    with open("web_researcher_config.json", "w") as f:
        json.dump(config, f, indent=2)

    print()
    print("Config saved to web_researcher_config.json")
    print("Now run: python web_researcher.py \"sua pesquisa aqui\"")

    return config


if __name__ == "__main__":
    setup()
