# Tool-server sandbox image. Contains only the MCP server and the standard library tools.
# No LangChain, no API keys, no network at runtime (docker run --network none).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app
RUN pip install --no-cache-dir "mcp>=1.2"
COPY src/secure_agents/__init__.py src/secure_agents/__init__.py
COPY src/secure_agents/roles.py src/secure_agents/roles.py
COPY src/secure_agents/tools.py src/secure_agents/tools.py
COPY src/secure_agents/mcp_server.py src/secure_agents/mcp_server.py

# nobody:nogroup. The workspace is mounted at runtime, read-only for docs.
USER 65534:65534
ENTRYPOINT ["python", "-m", "secure_agents.mcp_server"]
