"""MCP tool implementations for Backend Developer agent.

Each tool wraps an MCP client call or implements local logic relevant
to the Backend Developer's responsibilities: creating FastAPI endpoints,
SQLAlchemy models, Pydantic schemas, and managing code via GitHub MCP.
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any, Callable

import structlog
from pydantic import BaseModel, Field, ValidationError

from shared.mcp_client import MCPClient

logger = structlog.get_logger("backend_dev.tools")


# ---------------------------------------------------------------------------
# Pydantic schemas for tool inputs/outputs
# ---------------------------------------------------------------------------


class BranchInput(BaseModel):
    """Input for creating a git branch."""

    branch_name: str = Field(..., description="Name of the branch to create (e.g. 'feature/user-registration')")
    base_branch: str = Field(default="main", description="Base branch to create from")


class CommitInput(BaseModel):
    """Input for committing files to a branch."""

    branch: str = Field(..., description="Branch name to commit to")
    files: dict[str, str] = Field(..., description="Mapping of file_path -> file_content")
    message: str = Field(..., description="Commit message")


class PRInput(BaseModel):
    """Input for creating a pull request."""

    title: str = Field(..., description="PR title")
    body: str = Field(default="", description="PR body / description")
    head: str = Field(..., description="Head branch (source)")
    base: str = Field(default="main", description="Base branch (target)")


class GetFileInput(BaseModel):
    """Input for reading a file from the repository."""

    file_path: str = Field(..., description="Path to the file in the repo")
    ref: str | None = Field(default=None, description="Git ref (branch, tag, commit SHA)")


class SearchCodeInput(BaseModel):
    """Input for searching code in the repository."""

    query: str = Field(..., description="Search query string")
    file_extension: str | None = Field(default=None, description="Filter by file extension (e.g. 'py', 'ts')")


class LibraryDocsInput(BaseModel):
    """Input for fetching library documentation from Context7."""

    library_name: str = Field(
        ...,
        description="Library name (e.g. 'fastapi', 'sqlalchemy', 'pydantic')",
    )
    topic: str = Field(
        default="",
        description="Specific topic or question about the library",
    )
    max_tokens: int = Field(default=8000, ge=1000, le=32000, description="Max tokens in response")


class GenerateEndpointInput(BaseModel):
    """Input for generating a FastAPI endpoint."""

    method: str = Field(..., description="HTTP method (GET, POST, PUT, DELETE, PATCH)")
    path: str = Field(..., description="URL path (e.g. '/users/{user_id}')")
    summary: str = Field(default="", description="Short endpoint description")
    request_body_schema: dict[str, Any] | None = Field(
        default=None,
        description="Pydantic-style request body schema as dict",
    )
    response_schema: dict[str, Any] | None = Field(
        default=None,
        description="Expected response schema as dict",
    )
    status_codes: list[int] = Field(default=[200], description="Supported HTTP status codes")
    dependencies: list[str] = Field(default_factory=list, description="FastAPI dependency names")
    tags: list[str] = Field(default_factory=list, description="OpenAPI tags")


class GenerateModelInput(BaseModel):
    """Input for generating a SQLAlchemy model."""

    model_name: str = Field(..., description="Name of the SQLAlchemy model class")
    table_name: str = Field(..., description="Database table name")
    columns: list[dict[str, Any]] = Field(
        ...,
        description=(
            "List of column definitions. Each dict: "
            "{'name': str, 'type': str, 'nullable': bool, 'primary_key': bool, 'default': Any}"
        ),
    )
    relationships: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "List of relationship definitions. Each dict: "
            "{'name': str, 'target_model': str, 'type': 'one_to_many'|'many_to_one'|'one_to_one', 'foreign_key': str}"
        ),
    )
    indexes: list[dict[str, Any]] = Field(
        default_factory=list,
        description="List of index definitions. Each dict: {'columns': list[str], 'unique': bool}",
    )


class GeneratePydanticModelInput(BaseModel):
    """Input for generating a Pydantic schema model."""

    model_name: str = Field(..., description="Name of the Pydantic model class")
    fields: list[dict[str, Any]] = Field(
        ...,
        description=(
            "List of field definitions. Each dict: "
            "{'name': str, 'type': str, 'required': bool, 'default': Any, 'description': str}"
        ),
    )
    base_class: str = Field(default="BaseModel", description="Base class to inherit from")
    config: dict[str, Any] = Field(default_factory=dict, description="Pydantic model_config options")


class ValidatePythonInput(BaseModel):
    """Input for validating Python source code."""

    code: str = Field(..., description="Python source code to validate")
    check_imports: bool = Field(default=False, description="Also verify imports resolve correctly")


# ---------------------------------------------------------------------------
# SQL type mapping for SQLAlchemy code generation
# ---------------------------------------------------------------------------

SQLALCHEMY_TYPE_MAP: dict[str, str] = {
    "integer": "Integer",
    "int": "Integer",
    "bigint": "BigInteger",
    "smallint": "SmallInteger",
    "string": "String",
    "str": "String",
    "text": "Text",
    "boolean": "Boolean",
    "bool": "Boolean",
    "float": "Float",
    "numeric": "Numeric",
    "decimal": "Numeric",
    "datetime": "DateTime",
    "date": "Date",
    "time": "Time",
    "uuid": "Uuid",
    "json": "JSON",
    "jsonb": "JSON",
    "enum": "Enum",
}

PYDANTIC_TYPE_MAP: dict[str, str] = {
    "integer": "int",
    "int": "int",
    "bigint": "int",
    "smallint": "int",
    "string": "str",
    "str": "str",
    "text": "str",
    "boolean": "bool",
    "bool": "bool",
    "float": "float",
    "numeric": "Decimal",
    "decimal": "Decimal",
    "datetime": "datetime",
    "date": "date",
    "time": "time",
    "uuid": "UUID",
    "json": "dict[str, Any]",
    "list": "list[Any]",
    "optional": "Any | None",
}


# ---------------------------------------------------------------------------
# Tool factory — called by main.py to get tool callables
# ---------------------------------------------------------------------------


def get_tools(mcp_client: MCPClient, repo: str = "") -> dict[str, Callable]:
    """Return a mapping of tool names to async callables.

    Each callable accepts a single ``dict`` argument with the tool's
    parameters and returns a ``dict`` with the tool's result.

    Args:
        mcp_client: Shared MCP client for calling external MCP servers.
        repo: GitHub repository in ``owner/repo`` format.  Pulled from
            ``GITHUB_REPO`` env var if not supplied.

    Returns:
        Dict mapping tool name to its async callable.
    """
    repo = repo or os.environ.get("GITHUB_REPO", "")

    async def create_branch(params: dict) -> dict:
        """Create a new git branch via GitHub MCP.

        Args:
            params: Must conform to ``BranchInput`` schema.

        Returns:
            Dict with branch creation result.
        """
        try:
            inp = BranchInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info("creating_branch", branch=inp.branch_name, base=inp.base_branch)

        result = await mcp_client.call(
            server="github_mcp",
            tool="create_branch",
            arguments={
                "repo": repo,
                "branch": inp.branch_name,
                "base_branch": inp.base_branch,
            },
        )

        if result.get("isError"):
            logger.error("create_branch_failed", error=result)
            return {"success": False, "error": result.get("content", "Unknown error")}

        logger.info("branch_created", branch=inp.branch_name)
        return {
            "success": True,
            "branch": inp.branch_name,
            "base": inp.base_branch,
            "details": result.get("content", ""),
        }

    async def commit_files(params: dict) -> dict:
        """Commit one or more files to a branch via GitHub MCP.

        Args:
            params: Must conform to ``CommitInput`` schema.

        Returns:
            Dict with commit result including SHA.
        """
        try:
            inp = CommitInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info(
            "committing_files",
            branch=inp.branch,
            file_count=len(inp.files),
            message=inp.message,
        )

        result = await mcp_client.call(
            server="github_mcp",
            tool="commit_files",
            arguments={
                "repo": repo,
                "branch": inp.branch,
                "files": inp.files,
                "message": inp.message,
            },
        )

        if result.get("isError"):
            logger.error("commit_files_failed", error=result)
            return {"success": False, "error": result.get("content", "Unknown error")}

        logger.info("files_committed", branch=inp.branch, file_count=len(inp.files))
        return {
            "success": True,
            "branch": inp.branch,
            "files_committed": list(inp.files.keys()),
            "message": inp.message,
            "details": result.get("content", ""),
        }

    async def create_pull_request(params: dict) -> dict:
        """Create a pull request via GitHub MCP.

        Args:
            params: Must conform to ``PRInput`` schema.

        Returns:
            Dict with PR URL and number.
        """
        try:
            inp = PRInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info("creating_pr", title=inp.title, head=inp.head, base=inp.base)

        result = await mcp_client.call(
            server="github_mcp",
            tool="create_pr",
            arguments={
                "repo": repo,
                "title": inp.title,
                "body": inp.body,
                "head": inp.head,
                "base": inp.base,
            },
        )

        if result.get("isError"):
            logger.error("create_pr_failed", error=result)
            return {"success": False, "error": result.get("content", "Unknown error")}

        logger.info("pr_created", title=inp.title)
        return {
            "success": True,
            "title": inp.title,
            "head": inp.head,
            "base": inp.base,
            "details": result.get("content", ""),
        }

    async def get_file(params: dict) -> dict:
        """Read a file from the GitHub repository via MCP.

        Args:
            params: Must conform to ``GetFileInput`` schema.

        Returns:
            Dict with file content or error.
        """
        try:
            inp = GetFileInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info("getting_file", path=inp.file_path, ref=inp.ref)

        arguments: dict[str, Any] = {
            "repo": repo,
            "path": inp.file_path,
        }
        if inp.ref:
            arguments["ref"] = inp.ref

        result = await mcp_client.call(
            server="github_mcp",
            tool="get_file",
            arguments=arguments,
        )

        if result.get("isError"):
            logger.error("get_file_failed", path=inp.file_path, error=result)
            return {"success": False, "error": result.get("content", "Unknown error")}

        return {
            "success": True,
            "path": inp.file_path,
            "content": result.get("content", ""),
        }

    async def search_code(params: dict) -> dict:
        """Search code in the GitHub repository via MCP.

        Args:
            params: Must conform to ``SearchCodeInput`` schema.

        Returns:
            Dict with search results.
        """
        try:
            inp = SearchCodeInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info("searching_code", query=inp.query, ext=inp.file_extension)

        arguments: dict[str, Any] = {
            "repo": repo,
            "query": inp.query,
        }
        if inp.file_extension:
            arguments["file_extension"] = inp.file_extension

        result = await mcp_client.call(
            server="github_mcp",
            tool="search_code",
            arguments=arguments,
        )

        if result.get("isError"):
            logger.error("search_code_failed", error=result)
            return {"success": False, "error": result.get("content", "Unknown error")}

        return {
            "success": True,
            "query": inp.query,
            "results": result.get("content", ""),
        }

    async def get_library_docs(params: dict) -> dict:
        """Fetch library documentation from Context7 MCP.

        Looks up documentation for libraries like FastAPI, SQLAlchemy,
        Pydantic, etc. Useful for checking current API signatures and
        best practices before generating code.

        Args:
            params: Must conform to ``LibraryDocsInput`` schema.

        Returns:
            Dict with documentation content.
        """
        try:
            inp = LibraryDocsInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info("fetching_library_docs", library=inp.library_name, topic=inp.topic)

        # Step 1: Resolve library ID
        resolve_result = await mcp_client.call(
            server="context7",
            tool="resolve_library_id",
            arguments={"libraryName": inp.library_name},
        )

        if resolve_result.get("isError"):
            logger.error("resolve_library_failed", library=inp.library_name, error=resolve_result)
            return {"success": False, "error": f"Could not resolve library '{inp.library_name}': {resolve_result.get('content', '')}"}

        library_id = resolve_result.get("content", "")
        if not library_id:
            return {"success": False, "error": f"No library ID returned for '{inp.library_name}'"}

        # Step 2: Get library docs
        docs_arguments: dict[str, Any] = {
            "context7CompatibleLibraryID": library_id,
            "tokens": inp.max_tokens,
        }
        if inp.topic:
            docs_arguments["topic"] = inp.topic

        docs_result = await mcp_client.call(
            server="context7",
            tool="get_library_docs",
            arguments=docs_arguments,
        )

        if docs_result.get("isError"):
            logger.error("get_library_docs_failed", library=inp.library_name, error=docs_result)
            return {"success": False, "error": docs_result.get("content", "Unknown error")}

        logger.info("library_docs_fetched", library=inp.library_name, topic=inp.topic)
        return {
            "success": True,
            "library": inp.library_name,
            "topic": inp.topic,
            "docs": docs_result.get("content", ""),
        }

    async def generate_endpoint(params: dict) -> dict:
        """Generate a FastAPI endpoint implementation (local logic).

        Produces a complete FastAPI router endpoint with type hints,
        docstring, request/response models, error handling, and
        proper HTTP status codes.

        Args:
            params: Must conform to ``GenerateEndpointInput`` schema.

        Returns:
            Dict with generated Python code.
        """
        try:
            inp = GenerateEndpointInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info(
            "generating_endpoint",
            method=inp.method,
            path=inp.path,
            summary=inp.summary,
        )

        method_lower = inp.method.lower()
        valid_methods = {"get", "post", "put", "delete", "patch"}
        if method_lower not in valid_methods:
            return {"success": False, "error": f"Invalid HTTP method: {inp.method}. Must be one of {valid_methods}"}

        # Build function name from path
        func_name = _path_to_function_name(inp.path, method_lower)

        # Build parameters string
        path_params = re.findall(r"\{(\w+)\}", inp.path)
        params_str = ", ".join(f"{p}: str" for p in path_params)

        # Build request body if provided
        request_model_name = ""
        request_param = ""
        if inp.request_body_schema and method_lower in ("post", "put", "patch"):
            request_model_name = f"{_to_pascal_case(func_name)}Request"
            request_param = f", body: {request_model_name}"

        # Build response model name
        response_model_name = ""
        if inp.response_schema:
            response_model_name = f"{_to_pascal_case(func_name)}Response"

        # Build dependencies
        deps_str = ""
        if inp.dependencies:
            dep_items = ", ".join(f"{d}=Depends()" for d in inp.dependencies)
            deps_str = f", {dep_items}"

        # Build tags
        tags_str = ""
        if inp.tags:
            tags_repr = ", ".join(f'"{t}"' for t in inp.tags)
            tags_str = f", tags=[{tags_repr}]"

        # Status code
        status_code = inp.status_codes[0] if inp.status_codes else 200

        # Build response model annotation
        response_annotation = response_model_name if response_model_name else "dict[str, Any]"

        # Summary line
        summary_line = inp.summary or f"{inp.method.upper()} {inp.path}"

        # Generate the endpoint code
        code_lines = [
            f'@router.{method_lower}("{inp.path}", response_model={response_annotation}, status_code={status_code}{tags_str})',
            f"async def {func_name}(",
        ]

        # Parameters
        all_params = []
        if path_params:
            for p in path_params:
                all_params.append(f"    {p}: str")
        if request_param:
            all_params.append(f"    body: {request_model_name}")
        if deps_str:
            for d in inp.dependencies:
                all_params.append(f"    {d}: Any = Depends()")

        if all_params:
            code_lines.extend(all_params)
        else:
            code_lines.append("    # No parameters")

        code_lines.extend([
            f") -> {response_annotation}:",
            f'    """{summary_line}.',
            "",
            "    Args:",
        ])

        for p in path_params:
            code_lines.append(f"        {p}: Path parameter.")
        if request_model_name:
            code_lines.append(f"        body: Request body with {request_model_name} schema.")

        code_lines.extend([
            "",
            "    Returns:",
            f"        {response_annotation} with the result.",
            "",
            "    Raises:",
            "        HTTPException: If the resource is not found or validation fails.",
            '    """',
            "    try:",
            "        # TODO: Implement business logic here",
            f'        logger.info("{func_name}_called"',
        ])

        if path_params:
            code_lines[-1] += ", " + ", ".join(f'{p}={p}' for p in path_params)
        code_lines[-1] += ")"

        if response_model_name:
            code_lines.extend([
                f"        return {response_model_name}(",
                "            # TODO: Populate response fields",
                "        )",
            ])
        else:
            code_lines.extend([
                "        return {",
                '            "success": True,',
                '            "message": "Operation completed",',
                "            # TODO: Add response data",
                "        }",
            ])

        code_lines.extend([
            "    except HTTPException:",
            "        raise",
            "    except Exception as e:",
            f'        logger.error("{func_name}_error", error=str(e))',
            "        raise HTTPException(",
            "            status_code=500,",
            '            detail={"error": "Internal server error", "message": str(e)},',
            "        ) from e",
        ])

        code = "\n".join(code_lines)

        # Generate request model if needed
        request_model_code = ""
        if inp.request_body_schema and request_model_name:
            request_model_code = _generate_pydantic_model_from_dict(
                request_model_name, inp.request_body_schema
            )

        # Generate response model if needed
        response_model_code = ""
        if inp.response_schema and response_model_name:
            response_model_code = _generate_pydantic_model_from_dict(
                response_model_name, inp.response_schema
            )

        return {
            "success": True,
            "function_name": func_name,
            "endpoint_code": code,
            "request_model": request_model_code,
            "response_model": response_model_code,
            "method": inp.method,
            "path": inp.path,
        }

    async def generate_sqlalchemy_model(params: dict) -> dict:
        """Generate a SQLAlchemy ORM model class (local logic).

        Produces a complete SQLAlchemy model with columns, relationships,
        indexes, and proper type annotations.

        Args:
            params: Must conform to ``GenerateModelInput`` schema.

        Returns:
            Dict with generated Python code.
        """
        try:
            inp = GenerateModelInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info("generating_sqlalchemy_model", model=inp.model_name, table=inp.table_name)

        code_lines = [
            f"class {inp.model_name}(Base):",
            f'    """SQLAlchemy model for the ``{inp.table_name}`` table."""',
            "",
            f"    __tablename__ = \"{inp.table_name}\"",
            "",
        ]

        # Columns
        has_primary_key = False
        for col in inp.columns:
            col_name = col.get("name", "")
            col_type_str = col.get("type", "string").lower()
            nullable = col.get("nullable", False)
            is_pk = col.get("primary_key", False)
            default_val = col.get("default")

            if is_pk:
                has_primary_key = True

            sa_type = SQLALCHEMY_TYPE_MAP.get(col_type_str, "String")

            # Build column definition parts
            col_parts = [f"{sa_type}()"]
            if is_pk:
                col_parts.append("primary_key=True")
            if nullable:
                col_parts.append("nullable=True")
            elif not is_pk:
                col_parts.append("nullable=False")
            if default_val is not None:
                col_parts.append(f"default={repr(default_val)}")

            col_args = ", ".join(col_parts)
            code_lines.append(f"    {col_name} = Column({col_args})")

        # Ensure there's a primary key
        if not has_primary_key:
            code_lines.insert(3, "    id = Column(Integer, primary_key=True, autoincrement=True)")

        code_lines.append("")

        # Relationships
        for rel in inp.relationships:
            rel_name = rel.get("name", "")
            target = rel.get("target_model", "")
            rel_type = rel.get("type", "one_to_many")
            foreign_key = rel.get("foreign_key", "")

            if rel_type == "one_to_many":
                code_lines.append(f'    {rel_name} = relationship("{target}", back_populates="{inp.model_name.lower()}")')
            elif rel_type == "many_to_one":
                code_lines.append(f'    {rel_name} = relationship("{target}", back_populates="{inp.model_name.lower()}s")')
            elif rel_type == "one_to_one":
                code_lines.append(f'    {rel_name} = relationship("{target}", uselist=False, back_populates="{inp.model_name.lower()}")')

        if inp.relationships:
            code_lines.append("")

        # Indexes
        if inp.indexes:
            code_lines.extend([
                "",
                f"    __table_args__ = (",
            ])
            for idx in inp.indexes:
                idx_cols = idx.get("columns", [])
                unique = idx.get("unique", False)
                idx_name = f"idx_{inp.table_name}_{'_'.join(idx_cols)}"
                cols_repr = ", ".join(f'"{c}"' for c in idx_cols)
                unique_str = "True" if unique else "False"
                code_lines.append(f'        Index("{idx_name}", {cols_repr}, unique={unique_str}),')
            code_lines.append("    )")

        code = "\n".join(code_lines)

        return {
            "success": True,
            "model_name": inp.model_name,
            "table_name": inp.table_name,
            "code": code,
            "column_count": len(inp.columns),
            "relationship_count": len(inp.relationships),
        }

    async def generate_pydantic_model(params: dict) -> dict:
        """Generate a Pydantic model class (local logic).

        Produces a complete Pydantic v2 model with field definitions,
        type annotations, defaults, and model_config.

        Args:
            params: Must conform to ``GeneratePydanticModelInput`` schema.

        Returns:
            Dict with generated Python code.
        """
        try:
            inp = GeneratePydanticModelInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info("generating_pydantic_model", model=inp.model_name, field_count=len(inp.fields))

        code_lines = [
            f"class {inp.model_name}({inp.base_class}):",
            f'    """Pydantic model: {inp.model_name}."""',
            "",
        ]

        for field in inp.fields:
            fname = field.get("name", "")
            ftype_raw = field.get("type", "str")
            required = field.get("required", True)
            default = field.get("default")
            description = field.get("description", "")

            # Map type
            ftype = PYDANTIC_TYPE_MAP.get(ftype_raw.lower(), ftype_raw)

            # Build field definition
            field_parts = []

            if required and default is None:
                field_parts.append(f"{fname}: {ftype}")
            elif default is not None:
                if isinstance(default, str):
                    field_parts.append(f'{fname}: {ftype} = "{default}"')
                else:
                    field_parts.append(f"{fname}: {ftype} = {repr(default)}")
            else:
                field_parts.append(f"{fname}: {ftype} | None = None")

            # Add Field() with description if provided
            if description:
                # Rebuild with Field()
                if required and default is None:
                    field_parts = [f'{fname}: {ftype} = Field(..., description="{description}")']
                elif default is not None:
                    field_parts = [f'{fname}: {ftype} = Field(default={repr(default)}, description="{description}")']
                else:
                    field_parts = [f'{fname}: {ftype} | None = Field(default=None, description="{description}")']

            code_lines.extend(["    " + p for p in field_parts])

        # Add model_config if provided
        if inp.config:
            code_lines.append("")
            code_lines.append("    model_config = {")
            for key, value in inp.config.items():
                code_lines.append(f"        \"{key}\": {repr(value)},")
            code_lines.append("    }")

        code = "\n".join(code_lines)

        return {
            "success": True,
            "model_name": inp.model_name,
            "code": code,
            "field_count": len(inp.fields),
        }

    async def validate_python_syntax(params: dict) -> dict:
        """Validate Python source code syntax (local logic).

        Parses the code with ``ast.parse`` to check for syntax errors
        without executing it.

        Args:
            params: Must conform to ``ValidatePythonInput`` schema.

        Returns:
            Dict with validation result.
        """
        try:
            inp = ValidatePythonInput(**params)
        except ValidationError as e:
            return {"success": False, "error": f"Invalid input: {e}"}

        logger.info("validating_python_syntax", code_length=len(inp.code))

        errors = []
        warnings = []

        # Syntax check
        try:
            tree = ast.parse(inp.code)
        except SyntaxError as e:
            errors.append({
                "type": "SyntaxError",
                "message": str(e.msg),
                "line": e.lineno,
                "column": e.offset,
                "text": e.text,
            })
            return {
                "success": False,
                "valid": False,
                "errors": errors,
                "warnings": warnings,
            }

        # Analyze the AST for common issues
        for node in ast.walk(tree):
            # Check for bare except
            if isinstance(node, ast.ExceptHandler) and node.type is None:
                warnings.append({
                    "type": "BareExcept",
                    "message": "Bare 'except:' clause detected — prefer 'except Exception:'",
                    "line": node.lineno,
                })

            # Check for pass-only functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
                    warnings.append({
                        "type": "EmptyFunction",
                        "message": f"Function '{node.name}' contains only 'pass' — may need implementation",
                        "line": node.lineno,
                    })

            # Check for TODO comments
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str) and "TODO" in node.value.value.upper():
                    warnings.append({
                        "type": "TodoComment",
                        "message": f"TODO comment found: {node.value.value[:80]}",
                        "line": node.lineno,
                    })

        return {
            "success": True,
            "valid": True,
            "errors": errors,
            "warnings": warnings,
            "line_count": len(inp.code.splitlines()),
        }

    async def create_issue(params: dict) -> dict:
        """Create a GitHub issue via MCP.

        Useful for tracking bugs, feature requests, or documentation
        needs discovered during implementation.

        Args:
            params: Dict with 'title', optional 'body', optional 'labels'.

        Returns:
            Dict with issue creation result.
        """
        title = params.get("title", "")
        body = params.get("body", "")
        labels = params.get("labels", [])

        if not title:
            return {"success": False, "error": "title is required"}

        logger.info("creating_issue", title=title, labels=labels)

        result = await mcp_client.call(
            server="github_mcp",
            tool="create_issue",
            arguments={
                "repo": repo,
                "title": title,
                "body": body,
                "labels": labels,
            },
        )

        if result.get("isError"):
            logger.error("create_issue_failed", error=result)
            return {"success": False, "error": result.get("content", "Unknown error")}

        logger.info("issue_created", title=title)
        return {
            "success": True,
            "title": title,
            "details": result.get("content", ""),
        }

    # -----------------------------------------------------------------------
    # Return the tool registry
    # -----------------------------------------------------------------------

    return {
        "create_branch": create_branch,
        "commit_files": commit_files,
        "create_pull_request": create_pull_request,
        "get_file": get_file,
        "search_code": search_code,
        "get_library_docs": get_library_docs,
        "generate_endpoint": generate_endpoint,
        "generate_sqlalchemy_model": generate_sqlalchemy_model,
        "generate_pydantic_model": generate_pydantic_model,
        "validate_python_syntax": validate_python_syntax,
        "create_issue": create_issue,
    }


# ---------------------------------------------------------------------------
# Private helper functions
# ---------------------------------------------------------------------------


def _path_to_function_name(path: str, method: str) -> str:
    """Convert an API path and method to a Python function name.

    Examples:
        >>> _path_to_function_name("/users/{user_id}", "get")
        'get_user_by_user_id'
        >>> _path_to_function_name("/health", "get")
        'get_health'
        >>> _path_to_function_name("/api/v1/orders", "post")
        'create_api_v1_order'
    """
    # Remove leading/trailing slashes and API version prefixes
    clean = path.strip("/")
    clean = re.sub(r"^api/v\d+/", "", clean)

    # Split into segments
    segments = clean.split("/")

    parts = [method]
    for seg in segments:
        if seg.startswith("{") and seg.endswith("}"):
            param = seg[1:-1]
            parts.append(f"by_{param}")
        else:
            # Singularize simple plurals (users -> user)
            singular = re.sub(r"s$", "", seg) if seg.endswith("s") and not seg.endswith("ss") else seg
            parts.append(singular)

    return "_".join(parts)


def _to_pascal_case(snake: str) -> str:
    """Convert a snake_case string to PascalCase.

    Examples:
        >>> _to_pascal_case("get_user_by_id")
        'GetUserById'
    """
    return "".join(word.capitalize() for word in snake.split("_"))


def _generate_pydantic_model_from_dict(name: str, schema: dict[str, Any]) -> str:
    """Generate a Pydantic v2 model class string from a schema dict.

    Args:
        name: Model class name.
        schema: Dict mapping field names to their types/defaults.
            Values can be:
            - str (Python type name)
            - dict with 'type', 'default', 'description' keys

    Returns:
        Python source code string for the model class.
    """
    lines = [
        f"class {name}(BaseModel):",
        f'    """Auto-generated Pydantic model."""',
        "",
    ]

    for field_name, field_spec in schema.items():
        if isinstance(field_spec, str):
            ftype = field_spec
            default = None
            desc = ""
        elif isinstance(field_spec, dict):
            ftype = field_spec.get("type", "Any")
            default = field_spec.get("default")
            desc = field_spec.get("description", "")
        else:
            ftype = "Any"
            default = None
            desc = ""

        # Map common types
        ftype = PYDANTIC_TYPE_MAP.get(ftype.lower(), ftype)

        if desc:
            if default is not None:
                lines.append(f'    {field_name}: {ftype} = Field(default={repr(default)}, description="{desc}")')
            else:
                lines.append(f'    {field_name}: {ftype} = Field(..., description="{desc}")')
        elif default is not None:
            if isinstance(default, str):
                lines.append(f'    {field_name}: {ftype} = "{default}"')
            else:
                lines.append(f"    {field_name}: {ftype} = {repr(default)}")
        else:
            lines.append(f"    {field_name}: {ftype}")

    if not schema:
        lines.append("    pass")

    return "\n".join(lines)