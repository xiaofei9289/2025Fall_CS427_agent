# Refined Read Tool Documentation

## Overview

The refined `read_file` tool provides targeted line selection capabilities to reduce token usage, speed up agent runs, and keep agents focused on relevant code sections. This tool is designed to be minimal, safe, and line-centric.

**Key Capabilities:**
- 5 line selection strategies (lines, range, head, tail, around)
- Dual-mode operation (Docker/sandbox + host filesystem)
- SWEBench compatible with environment execution
- Token reduction via max_chars truncation
- Security features (path traversal protection, binary rejection)
- Optional comment stripping for common languages

## Features

### Line Selection Strategies

The tool supports five different line selection strategies (one per call):

1. **`lines`**: Read exact line numbers
2. **`range`**: Read inclusive line range (start to end)
3. **`head`**: Read first N lines
4. **`tail`**: Read last N lines
5. **`around`**: Read window around a specific line (with radius)

### Environment Support

- **SWEBench Compatible**: Works inside Docker containers via `env.execute()`
- **Dual Mode**: Automatically detects environment and uses appropriate method
  - With `env`: Executes bash commands (sed/head/tail) inside sandbox
  - Without `env`: Reads directly from host filesystem
- **Container-Aware**: Properly handles `/testbed` paths in SWEBench runs

### Safety & Performance

- **Path traversal protection**: Denies access outside repository root (host mode)
- **Binary file rejection**: Rejects files containing NUL bytes
- **Token reduction**: `max_chars` parameter (default: 20,000) truncates output
- **Line normalization**: CRLF automatically normalized to LF
- **UTF-8 handling**: Decodes with error replacement for unknown encodings

### Additional Features

- **Comment stripping**: Optional best-effort removal for `.py` and `//` languages
- **Structured output**: Returns JSON with metadata (path, encoding, start_line, line_count, truncated, content)
- **Boundary clamping**: Out-of-bounds line requests are clamped to file length

## API Reference

### Tool Name
`read_file`

### Parameters

```json
{
  "path": "src/module/file.py",
  "selector": {
    "lines": [12, 18, 24],
    "range": {"start": 50, "end": 80},
    "head": 200,
    "tail": 200,
    "around": {"line": 320, "radius": 20}
  },
  "strip_comments": false,
  "max_chars": 20000
}
```

#### Parameter Details

- **`path`** (required): Path to the file to read
- **`selector`** (optional): Line selection strategy (provide exactly one)
  - **`lines`**: Array of line numbers (1-indexed)
  - **`range`**: Object with `start` and `end` (inclusive, 1-indexed)
  - **`head`**: Integer, first N lines
  - **`tail`**: Integer, last N lines
  - **`around`**: Object with `line` (center) and `radius` (window size)
- **`strip_comments`** (optional, default: false): Remove comments from output
- **`max_chars`** (optional, default: 20000): Maximum characters in output

### Return Format

```json
{
  "path": "src/module/file.py",
  "encoding": "utf-8",
  "start_line": 301,
  "line_count": 41,
  "truncated": false,
  "content": "..."
}
```

#### Return Fields

- **`path`**: Original file path
- **`encoding`**: File encoding (always "utf-8")
- **`start_line`**: First line number in the result
- **`line_count`**: Number of lines returned
- **`truncated`**: Boolean indicating if content was truncated by max_chars
- **`content`**: The actual file content

## Usage Examples

### Example 1: Read Entire File

```json
{
  "path": "src/main.py"
}
```

### Example 2: Read Specific Lines

```json
{
  "path": "src/utils.py",
  "selector": {
    "lines": [10, 25, 42]
  }
}
```

### Example 3: Read Line Range

```json
{
  "path": "src/config.py",
  "selector": {
    "range": {"start": 50, "end": 100}
  }
}
```

### Example 4: Read First 50 Lines

```json
{
  "path": "README.md",
  "selector": {
    "head": 50
  }
}
```

### Example 5: Read Last 20 Lines

```json
{
  "path": "logs/error.log",
  "selector": {
    "tail": 20
  }
}
```

### Example 6: Read Window Around Line

```json
{
  "path": "src/module.py",
  "selector": {
    "around": {"line": 150, "radius": 10}
  }
}
```

This reads lines 140-160 (150 ± 10).

### Example 7: Strip Comments

```json
{
  "path": "src/app.py",
  "selector": {
    "head": 100
  },
  "strip_comments": true
}
```

### Example 8: Limit Output Size

```json
{
  "path": "large_file.txt",
  "max_chars": 5000
}
```

## Rationale

### Why Line-Based Access?

- **Matches diffs and patches**: Line numbers align with version control
- **Reduces tokens**: Only read relevant sections instead of entire files
- **Mirrors developer workflow**: Developers inspect code near stack traces or grep hits
- **Avoids complexity**: No AST parsing required, keeping the tool minimal

### Why Token Reduction Matters

- **Reduces rate limits**: Fewer tokens = fewer 429 errors
- **Lowers costs**: Pay for only what you need
- **Improves focus**: Agents stay focused on relevant code sections
- **Speeds up runs**: Less data to process and transmit

## Edge Cases

### Out-of-Bounds Lines

When requesting lines beyond the file length, the tool clamps to available lines:

```json
// File has 100 lines, request lines [50, 150, 200]
// Result: Only lines 50 returned
```

### Empty Results

Empty results are allowed (e.g., `tail: 0`):

```json
{
  "line_count": 0,
  "content": ""
}
```

### Line Ending Normalization

All line endings (CRLF, CR, LF) are normalized to LF (`\n`).

### Comment Stripping Limitations

Comment stripping is best-effort and uses simple heuristics:
- **Python**: Removes `#` comments (doesn't handle strings)
- **JS/TS/Java/C/C++/Go/Rust**: Removes `//` comments (doesn't handle strings)
- **Other languages**: No-op

## Security Considerations

### Path Traversal Protection

The tool resolves paths and denies access outside the repository root:

```python
# Denied
{"path": "../../../etc/passwd"}
{"path": "/etc/passwd"}
```

### Binary File Rejection

Files containing NUL bytes (`\x00`) are rejected:

```
Binary file rejected: image.png
```

### Character Limit Enforcement

The `max_chars` parameter is strictly enforced to prevent excessive output.

## Implementation Details

### Architecture

The tool uses a **dual-mode architecture** that automatically adapts based on execution context:

```
┌─────────────────────────────────────────┐
│         RefinedReadFile.__call__        │
│  (Entry point - detects environment)    │
└────────────┬────────────────────────────┘
             │
             ├─── env provided? ───┐
             │                     │
         YES │                     │ NO
             │                     │
             ▼                     ▼
┌────────────────────┐   ┌─────────────────────┐
│ _execute_in_env()  │   │ _execute_on_host()  │
│ (Docker/Sandbox)   │   │ (Local filesystem)  │
├────────────────────┤   ├─────────────────────┤
│ • Build bash cmd   │   │ • Resolve path      │
│ • env.execute()    │   │ • Read file bytes   │
│ • Process output   │   │ • Apply selector    │
│ • Return JSON      │   │ • Return JSON       │
└────────────────────┘   └─────────────────────┘
```

### File Location

- **Tool implementation**: `src/minisweagent/tools/read.py` (~450 lines)
- **Test suite**: `tests/tools/test_read.py` (~250 lines)
- **Registration**: Imported in `src/minisweagent/run/extra/swebench.py`

### Key Methods

| Method | Purpose | Mode |
|--------|---------|------|
| `__call__()` | Entry point, detects environment | Both |
| `_execute_in_env()` | Execute in Docker/sandbox | Environment |
| `_execute_on_host()` | Execute on host filesystem | Host |
| `_build_bash_command()` | Generate sed/head/tail commands | Environment |
| `_apply_selector()` | Python-based line selection | Host |
| `_get_start_line_from_selector()` | Calculate start line number | Environment |
| `_resolve_path()` | Path validation and security | Host |
| `_strip_comments()` | Remove comments from lines | Both |

### Dependencies

- **Standard library only** (no external dependencies)
- `pathlib` - Path handling and resolution
- `json` - Structured output formatting
- `shlex` - Safe command quoting in environment mode
- `re` - Comment stripping (minimal usage)

### Performance

- **Host mode**: 
  - Reads entire file into memory (suitable for source code files)
  - Line selection via Python slicing (O(n) where n = file lines)
  - Memory usage: ~2x file size (bytes + decoded text)
  
- **Environment mode**: 
  - Uses efficient bash commands (sed/head/tail)
  - Streaming execution (no full file load in Python)
  - Memory usage: Only selected lines loaded
  
- **Comment stripping**: Simple regex (O(n) where n = selected lines)
- **Truncation**: String slicing (O(1) operation)

### Environment Execution

When an environment is provided (e.g., Docker in SWEBench), the tool uses bash commands via `env.execute()`:

| Selector | Bash Command Example | Description |
|----------|---------------------|-------------|
| **lines** | `sed -n '10p;25p;42p' file.py` | Extract specific line numbers |
| **range** | `sed -n '50,100p' file.py` | Extract inclusive line range |
| **head** | `head -n 50 file.py` | First N lines |
| **tail** | `tail -n 20 file.py` | Last N lines |
| **around** | `sed -n '140,160p' file.py` | Window around center line |
| **none** | `cat -- file.py` | Entire file (no selector) |

**Why bash commands?**
- Works inside Docker containers where Python can't access host filesystem
- Efficient for large files (streaming vs loading into memory)
- Standard Unix tools available in all SWEBench containers
- Matches cs427_tools_extension.md requirements

**Execution Flow:**
1. Tool receives `env` parameter from agent
2. Builds appropriate bash command based on selector
3. Executes command via `env.execute()` inside container
4. Processes output (normalize line endings, strip comments, truncate)
5. Returns structured JSON result

## Testing

The tool includes comprehensive tests covering:

### Test Categories

1. **Selector Tests** (6 tests)
   - `test_read_lines_selector` - Exact line numbers
   - `test_read_range_selector` - Line ranges
   - `test_read_head_selector` - First N lines
   - `test_read_tail_selector` - Last N lines
   - `test_read_around_selector` - Window around line
   - `test_read_entire_file` - No selector (full file)

2. **Feature Tests** (4 tests)
   - `test_max_chars_truncation` - Output size limiting
   - `test_strip_comments_python` - Comment removal
   - `test_crlf_normalization` - Line ending normalization
   - `test_empty_tail` - Empty result handling

3. **Security Tests** (3 tests)
   - `test_path_traversal_denied` - Path traversal protection
   - `test_binary_file_rejection` - Binary file detection
   - `test_file_not_found` - Missing file handling

4. **Edge Case Tests** (7 tests)
   - `test_out_of_bounds_lines_clamped` - Line clamping
   - `test_range_clamping` - Range boundary handling
   - `test_multiple_selectors_error` - Validation
   - `test_invalid_range_start_greater_than_end` - Error cases
   - `test_missing_path` - Required parameter validation
   - And more...

### Running Tests

```bash
# Run all tests
pytest tests/tools/test_read.py -v

# Run specific test
pytest tests/tools/test_read.py::test_read_around_selector -v

# Run with coverage
pytest tests/tools/test_read.py --cov=src/minisweagent/tools/read
```

### Test Results

- ✅ 20+ test cases
- ✅ All selectors covered
- ✅ All edge cases tested
- ✅ Security features validated
- ✅ Error handling verified

## Troubleshooting

### Common Issues

**Issue: "Path traversal denied"**
```
Solution: Ensure the path is within the repository root. Absolute paths 
outside the repo and .. traversal are blocked for security.
```

**Issue: "Binary file rejected"**
```
Solution: The file contains NUL bytes (\x00). This tool is designed for 
text files only. Use a different method for binary files.
```

**Issue: "File not found" in Docker**
```
Solution: In SWEBench, files are in /testbed. Use absolute paths like 
"/testbed/src/app.py" or relative paths from the working directory.
```

**Issue: Empty result when using `lines` selector**
```
Solution: Check that line numbers exist in the file. Out-of-bounds lines 
are silently skipped (clamped behavior).
```

**Issue: Output truncated unexpectedly**
```
Solution: Check the max_chars parameter. Default is 20,000 characters. 
Increase if needed: {"max_chars": 50000}
```

### Debugging Tips

1. **Test without selector first**: Verify file access works
   ```json
   {"path": "src/app.py"}
   ```

2. **Check line count**: Use `head` to see if file has expected lines
   ```json
   {"path": "src/app.py", "selector": {"head": 10}}
   ```

3. **Verify environment mode**: Check if `env` parameter is being passed
   - With env: Uses bash commands
   - Without env: Uses Python file I/O

## Future Enhancements

Potential improvements for future versions:

### Planned Features
- **AST-based selection**: Read specific functions or classes by name
- **Syntax highlighting**: Color-coded output for better readability
- **Multi-file reading**: Read multiple files in a single call
- **Regex-based filtering**: Select lines matching a pattern
- **Diff-aware reading**: Only read changed lines from git diff

### Performance Optimizations
- **Streaming for large files**: Don't load entire file in host mode
- **Caching**: Cache frequently accessed files
- **Parallel reads**: Read multiple files concurrently

### Language Support
- **More comment styles**: Support for more programming languages
- **String-aware parsing**: Handle comments inside strings correctly
- **Block comment removal**: Remove /* */ and """ """ style comments
