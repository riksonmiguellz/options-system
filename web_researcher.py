"""
Web Researcher — give an order, get results.

Usage:
    export ANTHROPIC_API_KEY="your-api-key"
    python web_researcher.py "pesquise sobre volatilidade implícita no mercado brasileiro"
"""

import json
import sys

import anthropic


def load_config():
    try:
        with open("web_researcher_config.json") as f:
            return json.load(f)
    except FileNotFoundError:
        print("Config not found. Run setup first:")
        print("  python setup_web_researcher.py")
        sys.exit(1)


def research(query: str):
    config = load_config()
    client = anthropic.Anthropic()

    # Create a session for this research task
    session = client.beta.sessions.create(
        agent={
            "type": "agent",
            "id": config["agent_id"],
            "version": config["agent_version"],
        },
        environment_id=config["environment_id"],
    )
    print(f"Session: {session.id}")
    print(f"Pesquisando: {query}")
    print("-" * 60)

    # Stream-first: open stream before sending the message
    with client.beta.sessions.stream(session_id=session.id) as stream:
        # Send the research query
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": query}],
                }
            ],
        )

        # Process events until done
        for event in stream:
            if event.type == "agent.message":
                for block in event.content:
                    if block.type == "text":
                        print(block.text, end="", flush=True)

            elif event.type == "agent.tool_use":
                print(f"\n  [tool: {event.tool_name}]", flush=True)

            elif event.type == "session.status_idle":
                if getattr(event, "stop_reason", None) and event.stop_reason.type != "requires_action":
                    break

            elif event.type == "session.status_terminated":
                break

    print("\n" + "-" * 60)
    print("Pesquisa concluída.")

    # Clean up
    client.beta.sessions.archive(session_id=session.id)


def main():
    if len(sys.argv) < 2:
        print("Uso: python web_researcher.py \"sua pesquisa aqui\"")
        print()
        print("Exemplos:")
        print('  python web_researcher.py "últimas notícias sobre Ibovespa"')
        print('  python web_researcher.py "melhores estratégias de opções para mercado lateral"')
        print('  python web_researcher.py "compare preços de PETR4 e VALE3 hoje"')
        sys.exit(1)

    query = " ".join(sys.argv[1:])
    research(query)


if __name__ == "__main__":
    main()
