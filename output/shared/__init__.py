# OpenCrew - Shared Module
# This module contains common utilities used across all agents in the OpenCrew system.
#
# Submodules:
#   - a2a_client:   Agent-to-Agent communication client
#   - a2a_server:   Base class for A2A server endpoints
#   - mcp_client:   MCP (Model Context Protocol) tool caller
#   - task_queue:   Async task queue backed by Redis
#   - models:       Shared Pydantic data models
#   - registry:     Agent auto-discovery registry