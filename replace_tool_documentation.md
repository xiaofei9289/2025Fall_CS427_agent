# Replace Tool Documentation

## Overview

The `replace` tool is a file text replacement utility integrated into the mini-swe-agent framework. It provides a safe, literal text search-and-replace capability that works both in local environments and within Docker sandboxes (e.g., SWEBench). The tool performs exact string matching rather than regex-based replacement, ensuring predictable behavior and reducing security risks.

## Tool Specification

### Tool Name
`replace`

### Description
Searches for and replaces text in a file within the workspace. Supports replacing either the first occurrence or all occurrences of the target text.

### Parameters

The tool accepts a JSON object with the following schema:

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "Path to the file to modify"
    },
    "old_text": {
      "type": "string",
      "description": "Exact text content to search for"
    },
    "new_text": {
      "type": "string",
      "description": "Text content to replace the matched text"
    },
    "replace_all": {
      "type": "boolean",
      "description": "If true, replace all occurrences; if false, replace only the first occurrence",
      "default": true
    }
  },
  "required": ["path", "old_text", "new_text"],
  "additionalProperties": false
}
```

### Return Value

The tool returns a dictionary with the following structure:

```python
{
    "output": str,      # Human-readable message describing the result
    "returncode": int   # Exit code: 0 for success, non-zero for errors
}
```

**Return Codes:**
- `0`: Success (replacement completed or no matches found)
- `1`: General error (file I/O issues, encoding problems)
- `2`: Validation error (missing path, empty old_text, invalid path)
- `13`: Permission denied

## Implementation Details

### Architecture

The `ReplaceTool` class implements the `Tool` protocol defined in `minisweagent.tools`. It is automatically registered in the global tool registry upon module import.

### Dual Execution Modes

The tool operates in two distinct modes depending on the execution context:

#### 1. Docker Environment Mode (SWEBench)

When an `env` parameter is provided (typically a Docker sandbox environment):

- **Path Validation**: The tool validates that the target path is within `/testbed` using `realpath` to prevent directory traversal attacks.
- **Execution Method**: Uses `sed` command executed via `env.execute()` to perform replacements within the container.
- **Text Escaping**: Special characters in both `old_text` and `new_text` are escaped using the `_escape_for_sed()` method to ensure safe `sed` command construction.

#### 2. Local Environment Mode

When no `env` parameter is provided:

- **File Operations**: Directly reads and writes files using Python's `pathlib` module.
- **Path Resolution**: Expands user home directory (`~`) and resolves to absolute paths.
- **Encoding**: Uses UTF-8 encoding with error replacement for malformed sequences.

### Text Escaping Strategy

The `_escape_for_sed()` static method handles character escaping for safe `sed` command construction:

1. **Backslash Escaping**: Escaped first (critical for proper escaping order)
2. **Delimiter Escaping**: Escapes `/` characters (sed delimiter)
3. **Newline Escaping**: Converts newlines to `\n` sequences
4. **Pattern-Specific Escaping**:
   - For `old_text` (pattern): Escapes regex special characters: `.`, `*`, `[`, `]`, `^`, `$`
   - For `new_text` (replacement): Escapes the `&` character (sed replacement special character)

This ensures that literal text matching is preserved even when the text contains special characters.

### Replacement Logic

- **Replace All Mode** (`replace_all=True`):
  - Counts all occurrences using `str.count()`
  - Replaces all matches using `str.replace()`
  
- **Replace First Mode** (`replace_all=False`):
  - Uses `str.find()` to locate the first occurrence
  - Manually constructs the new content by concatenating prefix, replacement, and suffix

## Usage Examples

### Example 1: Replace All Occurrences

```python
from minisweagent.tools import REGISTRY
import minisweagent.tools.replace

replace_tool = REGISTRY["replace"]
result = replace_tool({
    "path": "example.py",
    "old_text": "def old_function",
    "new_text": "def new_function",
    "replace_all": True
})
# Result: {"output": "Successfully replaced 3 occurrence(s) in example.py", "returncode": 0}
```

### Example 2: Replace First Occurrence Only

```python
result = replace_tool({
    "path": "config.txt",
    "old_text": "debug=True",
    "new_text": "debug=False",
    "replace_all": False
})
# Only the first occurrence is replaced
```

### Example 3: Multiline Text Replacement

```python
result = replace_tool({
    "path": "file.txt",
    "old_text": "line1\nline2",
    "new_text": "new1\nnew2",
    "replace_all": True
})
# Handles newlines correctly
```

### Example 4: Special Characters

```python
result = replace_tool({
    "path": "price.txt",
    "old_text": "$10.00",
    "new_text": "$20.00",
    "replace_all": True
})
# Special characters like $ are handled safely
```

## Common Use Cases

The replace tool is particularly useful for the following software engineering tasks:

### 1. Bug Fixing

**Scenario**: Fix incorrect function calls or variable names

```python
# Fix a typo in function call
replace_tool({
    "path": "src/api/client.py",
    "old_text": "response = fetch_usr_data()",
    "new_text": "response = fetch_user_data()",
    "replace_all": True
})
```

**Scenario**: Update incorrect constant values

```python
# Fix timeout value
replace_tool({
    "path": "config/settings.py",
    "old_text": "TIMEOUT = 30",
    "new_text": "TIMEOUT = 60",
    "replace_all": False
})
```

### 2. Refactoring

**Scenario**: Rename functions across codebase

```python
# Rename deprecated function
replace_tool({
    "path": "utils/helpers.py",
    "old_text": "def calculate_total(items):",
    "new_text": "def compute_total_cost(items):",
    "replace_all": False
})
```

**Scenario**: Update import statements

```python
# Update import path after module reorganization
replace_tool({
    "path": "src/main.py",
    "old_text": "from utils import helper",
    "new_text": "from core.utils import helper",
    "replace_all": True
})
```

### 3. Configuration Updates

**Scenario**: Toggle feature flags

```python
# Enable feature flag
replace_tool({
    "path": "config/features.json",
    "old_text": '"new_ui_enabled": false',
    "new_text": '"new_ui_enabled": true',
    "replace_all": False
})
```

**Scenario**: Update environment-specific settings

```python
# Switch to production database
replace_tool({
    "path": ".env",
    "old_text": "DB_HOST=localhost",
    "new_text": "DB_HOST=prod.example.com",
    "replace_all": True
})
```

### 4. Documentation Updates

**Scenario**: Update API endpoint documentation

```python
# Update deprecated endpoint in docs
replace_tool({
    "path": "docs/api.md",
    "old_text": "POST /api/v1/users",
    "new_text": "POST /api/v2/users",
    "replace_all": True
})
```

**Scenario**: Fix code examples in documentation

```python
# Update code example
replace_tool({
    "path": "README.md",
    "old_text": "client.connect()",
    "new_text": "client.connect(timeout=30)",
    "replace_all": True
})
```

### 5. Dependency Management

**Scenario**: Update package versions

```python
# Upgrade dependency version
replace_tool({
    "path": "requirements.txt",
    "old_text": "requests==2.28.0",
    "new_text": "requests==2.31.0",
    "replace_all": False
})
```

**Scenario**: Fix package name after migration

```python
# Update package name
replace_tool({
    "path": "setup.py",
    "old_text": 'install_requires=["old-package"]',
    "new_text": 'install_requires=["new-package"]',
    "replace_all": True
})
```

### 6. Code Style Enforcement

**Scenario**: Fix inconsistent string quotes

```python
# Standardize to double quotes
replace_tool({
    "path": "src/validators.py",
    "old_text": "logger.info('Processing data')",
    "new_text": 'logger.info("Processing data")',
    "replace_all": True
})
```

**Scenario**: Update deprecated syntax

```python
# Replace old-style string formatting
replace_tool({
    "path": "utils/format.py",
    "old_text": 'message = "User: %s" % username',
    "new_text": 'message = f"User: {username}"',
    "replace_all": True
})
```

### 7. Security Patches

**Scenario**: Fix hardcoded credentials

```python
# Remove hardcoded password
replace_tool({
    "path": "config/db.py",
    "old_text": 'PASSWORD = "admin123"',
    "new_text": 'PASSWORD = os.getenv("DB_PASSWORD")',
    "replace_all": True
})
```

**Scenario**: Update vulnerable function calls

```python
# Replace unsafe eval with safe alternative
replace_tool({
    "path": "src/parser.py",
    "old_text": "result = eval(user_input)",
    "new_text": "result = ast.literal_eval(user_input)",
    "replace_all": True
})
```

### 8. Test Updates

**Scenario**: Update test assertions after API changes

```python
# Update expected return value
replace_tool({
    "path": "tests/test_api.py",
    "old_text": 'assert response.status == 200',
    "new_text": 'assert response.status_code == 200',
    "replace_all": True
})
```

**Scenario**: Fix test fixtures

```python
# Update mock return value
replace_tool({
    "path": "tests/conftest.py",
    "old_text": "return {'status': 'ok'}",
    "new_text": "return {'status': 'success', 'code': 200}",
    "replace_all": False
})
```

### 9. Multi-line Code Blocks

**Scenario**: Replace entire class methods

```python
# Replace deprecated method implementation
replace_tool({
    "path": "src/models/user.py",
    "old_text": """    def save(self):
        db.save(self)
        return True""",
    "new_text": """    def save(self):
        db.session.add(self)
        db.session.commit()
        return self.id""",
    "replace_all": False
})
```

**Scenario**: Update SQL queries

```python
# Fix SQL injection vulnerability
replace_tool({
    "path": "database/queries.py",
    "old_text": '''query = f"SELECT * FROM users WHERE id = {user_id}"''',
    "new_text": '''query = "SELECT * FROM users WHERE id = ?"
cursor.execute(query, (user_id,))''',
    "replace_all": True
})
```

### 10. SWEBench-Specific Scenarios

**Scenario**: Fix failing tests in containerized environment

```python
# Inside Docker container at /testbed
replace_tool({
    "path": "/testbed/tests/test_integration.py",
    "old_text": "def test_old_behavior():",
    "new_text": "def test_new_behavior():",
    "replace_all": False
}, env=docker_env)
```

**Scenario**: Apply patch to repository code

```python
# Fix bug in target repository
replace_tool({
    "path": "/testbed/src/core/engine.py",
    "old_text": "if value > 0:",
    "new_text": "if value >= 0:",
    "replace_all": True
}, env=docker_env)
```

### Best Practices

When using the replace tool, consider these guidelines:

1. **Use Sufficient Context**: Include enough surrounding code to ensure unique matches
   ```python
   # Better: Include function signature
   old_text = "def process_data(items):\n    return items"
   
   # Worse: Too generic, might match multiple locations
   old_text = "return items"
   ```

2. **Handle Edge Cases**: Consider whitespace and indentation carefully
   ```python
   # Preserve exact indentation
   old_text = "    def method():"  # 4 spaces
   new_text = "    def method():"  # Keep same indentation
   ```

3. **Verify Before Replacing**: Use read_file to confirm the exact text exists
   ```python
   # First, read and verify
   content = read_file({"path": "file.py"})
   # Then replace with exact match
   replace_tool({"path": "file.py", "old_text": "...", "new_text": "..."})
   ```

4. **Choose replace_all Carefully**: 
   - Use `replace_all=True` for renaming variables/functions consistently
   - Use `replace_all=False` when updating a specific instance

5. **Escape Special Characters Properly**: The tool handles this automatically, but be aware of how your text will be interpreted in Docker mode

## Error Handling

### Validation Errors

- **Missing Path**: Returns `returncode: 2` with message "missing path"
- **Empty old_text**: Returns `returncode: 2` with message "old_text empty is not allowed"
- **Invalid Path (Docker)**: Returns `returncode: 2` if path is outside `/testbed`

### File System Errors

- **File Not Found**: Returns `returncode: 2` with message "File not found: {path}"
- **Permission Denied**: Returns `returncode: 13` with appropriate error message
- **General I/O Errors**: Returns `returncode: 1` with error details

### No Match Found

When `old_text` is not found in the file:
- Returns `returncode: 0` (treated as success)
- Output message: "No replacements made (text not found)"
- File remains unchanged

## Security Considerations

### Path Validation

In Docker environments, the tool enforces strict path validation:
- Uses `realpath` to resolve and normalize paths
- Rejects any path that does not resolve to a location under `/testbed`
- Prevents directory traversal attacks

### Literal Text Matching

- The tool performs **exact string matching**, not regex matching
- This prevents injection attacks through malicious patterns
- Special characters are escaped for `sed` but treated as literals in the search

### Safe Command Construction

- Uses `shlex.quote()` for path arguments in shell commands
- Implements comprehensive character escaping for `sed` commands
- Prevents command injection vulnerabilities

## Integration with mini-swe-agent

### Registration

The tool is automatically registered when the module is imported:

```python
import minisweagent.tools.replace  # Tool is registered automatically
```

### Agent Usage

The agent can invoke the tool using the following format:

```markdown
```tool
{"name": "replace", "args": {"path": "file.py", "old_text": "old", "new_text": "new"}}
```
```

### SWEBench Integration

For SWEBench runs, the tool must be imported in `src/minisweagent/run/extra/swebench.py` to ensure availability during batch evaluations.

## Testing

The tool includes comprehensive test coverage in `tests/tools/test_replace.py`, covering:

- Basic replacement operations (single and multiple occurrences)
- Edge cases (empty files, missing files, text not found)
- Parameter validation (missing path, empty old_text)
- Special characters and Unicode support
- Multiline text replacement
- Default parameter behavior

## Limitations

1. **Literal Matching Only**: The tool does not support regex patterns or wildcards
2. **No Backup**: Files are modified in-place without creating backup copies
3. **Encoding Assumption**: Assumes UTF-8 encoding (with error replacement for invalid sequences)
4. **Single File**: Only processes one file per invocation

## Future Enhancements

Potential improvements could include:
- Support for regex-based matching (with explicit opt-in)
- Backup file creation before modification
- Batch file processing
- Dry-run mode to preview changes


