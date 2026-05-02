# Adapter

## Probleme
Deux composants ont des interfaces incompatibles et ne peuvent pas collaborer directement. Modifier l'un ou l'autre casserait d'autres dependances.

## Solution
Un adapteur enveloppe l'interface existante et la traduit vers l'interface attendue. Le code appelant utilise l'interface cible sans savoir qu'un adapteur est en jeu.

## Exemple
```python
class MCPToolAdapter:
    """Adapte un serveur MCP stdio en tool LangChain."""

    def __init__(self, mcp_server: str, tool_name: str):
        self.mcp_server = mcp_server
        self.tool_name = tool_name

    async def invoke(self, input_data: dict) -> str:
        """Interface LangChain Tool.invoke()."""
        # Traduit l'appel LangChain vers le protocole MCP stdio
        session = await create_mcp_session(self.mcp_server)
        result = await session.call_tool(self.tool_name, input_data)
        return result.content[0].text

# Usage : LangChain utilise l'adapteur comme un tool standard
github_tool = MCPToolAdapter("npx @modelcontextprotocol/server-github", "search_repos")
result = await github_tool.invoke({"query": "langgraph python"})
```

## Quand l'utiliser
- Integrer un composant externe dont on ne controle pas l'interface (MCP stdio, API tierce)
- Unifier plusieurs implementations sous une interface commune (channels Discord/Email)
- Wrapper une librairie pour isoler le code metier de ses changements d'API
- Migration progressive d'une ancienne API vers une nouvelle

## Quand ne PAS l'utiliser
- On controle les deux interfaces et peut les harmoniser directement
- L'adaptation est triviale (un simple appel de methode)
