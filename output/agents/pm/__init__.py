"""PM agent module.

The Project Manager (PM) agent is responsible for:
- Reading the PRD from the PO agent
- Breaking work into Stories and Tasks with effort estimation (S/M/L/XL)
- Creating sprint plans and assigning Stories via Linear
- Tracking progress and unblocking dependencies in real-time
- Pushing work to both BA and Solution Architect agents in parallel
"""

from __future__ import annotations