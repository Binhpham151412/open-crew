"""OpenCrew — Business Analyst (BA) Agent Module.

The BA agent reads Stories from the PM and produces:

* User Stories with Gherkin-style Acceptance Criteria
* API contracts (OpenAPI YAML)
* Data models (entities, relations, constraints)

It pushes work asynchronously to Frontend Dev and Backend Dev in parallel.
"""

__all__: list[str] = []