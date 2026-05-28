"""
TechLead agent module.

The TechLead agent serves as the final gate in the OpenCrew pipeline.
It does NOT assign tasks or write code — instead it:

1. Arbitrates conflicts between agents (after round 3 debate)
2. Performs final architecture review
3. Merges PRs and signs-off delivery
4. Monitors the pipeline and unblocks agents stuck > 30 minutes

Port: 8010
Protocol: A2A (Agent-to-Agent)
MCP Tools: github_mcp, linear_mcp
"""