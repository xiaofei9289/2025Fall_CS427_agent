# Read Many Files Tool Documentation

## Overview

The `read_many_files` tool enables reading multiple files at once with intelligent content management and succinct representation. This tool is designed to help agents efficiently gather information from multiple files without making separate read calls for each file, reducing API calls and improving performance.

## Tool Specification

### Tool Name
`read_many_files`

### Description
Read multiple files at once with optional line limits per file. Returns a structured summary with file contents and metadata.

### Parameters

```json
{
  "type": "object",
  "properties": {
    "paths": {
      "type": "array",
      "items": {"type": "string"},
      "description": "List of file paths to read",
      "minItems": 1,
      "maxItems": 20
    },
    "max_lines_per_file": {
      "type": "integer",
      "minimum": 1,
      "description": "Maximum lines to read from each file (default: 100)",
      "default": 100
    },
    "include_metadata": {
      "type": "boolean",
      "description": "Include file metadata (size, line count, etc.) (default: true)",
      "default": true
    },
    "strip_empty_lines": {
      "type": "boolean",
      "description": "Remove empty lines from output (default: false)",
      "default": false
    },
    "max_total_chars": {
      "type": "integer",
      "minimum": 100,
      "description": "Hard cap on total output characters (default: 50000)",
      "default": 50000
    }
  },
  "required": ["paths"],
  "additionalProperties": false
}
```

### Return Value

The tool returns a dictionary with the following structure:

```python
{
    "output": str,      # JSON string containing structured results
    "returncode": int   # Exit code: 0 for success, non-zero for errors
}
```

**Return Codes:**
- `0`: Success (files processed, may include individual file errors)
- `2`: Validation error (missing/invalid paths, too many files)

## Usage Examples

### Basic Usage

```python
# Read multiple configuration files
tool({
    "paths": ["config/settings.json", "config/database.yml", ".env"]
})
```

### With Line Limits

```python
# Read first 50 lines of each file to get overview
tool({
    "paths": ["src/main.py", "src/utils.py", "src/models.py"],
    "max_lines_per_file": 50
})
```

### Clean Output Without Metadata

```python
# Get just content without file metadata
tool({
    "paths": ["README.md", "CHANGELOG.md"],
    "include_metadata": false,
    "strip_empty_lines": true
})
```

### Limited Total Output

```python
# Limit total characters for token management
tool({
    "paths": ["large_file1.txt", "large_file2.txt", "large_file3.txt"],
    "max_total_chars": 10000,
    "max_lines_per_file": 200
})
```

## Output Format

The tool returns a JSON structure with the following format:

```json
{
  "files_processed": 3,
  "files_successful": 2,
  "files_failed": 1,
  "files_skipped": 0,
  "total_characters": 1234,
  "results": [
    {
      "path": "/path/to/file1.txt",
      "status": "success",
      "content": "File content here...",
      "line_count": 45,
      "truncated_for_line_limit": false,
      "truncated_for_char_limit": false,
      "size_bytes": 1024,
      "total_lines": 45
    },
    {
      "path": "/path/to/file2.txt",
      "status": "error",
      "error": "File not found"
    }
  ]
}
```

## Common Use Cases

### 1. Configuration File Overview
```python
# Get overview of all config files
tool({
    "paths": [
        "package.json",
        "tsconfig.json", 
        ".eslintrc.json",
        "webpack.config.js"
    ],
    "max_lines_per_file": 30
})
```

### 2. Related Source Files
```python
# Read related Python modules together
tool({
    "paths": [
        "src/models/user.py",
        "src/models/profile.py",
        "src/models/__init__.py"
    ]
})
```

### 3. Documentation Batch Read
```python
# Read all markdown documentation
tool({
    "paths": [
        "README.md",
        "CONTRIBUTING.md",
        "docs/installation.md",
        "docs/usage.md"
    ],
    "strip_empty_lines": true
})
```

### 4. Log File Analysis
```python
# Read recent log files with limits
tool({
    "paths": [
        "logs/app.log",
        "logs/error.log",
        "logs/access.log"
    ],
    "max_lines_per_file": 100,
    "max_total_chars": 20000
})
```

## Features

### Token Management
- **Line Limits**: Control how many lines are read from each file
- **Character Limits**: Hard cap on total output to prevent token overflow
- **Truncation Indicators**: Clear indicators when content is truncated
- **Empty Line Stripping**: Option to remove empty lines for cleaner output

### Error Handling
- **Individual File Errors**: Continues processing other files if one fails
- **Binary File Detection**: Automatically rejects binary files
- **Permission Handling**: Graceful handling of permission denied errors
- **Path Validation**: Security checks and path resolution

### Performance Features
- **Batch Processing**: Single call processes multiple files
- **Metadata Options**: Optional metadata to reduce output size
- **Efficient Execution**: Uses optimized commands in Docker environments

### Safety Features
- **File Limit**: Maximum 20 files per call to prevent abuse
- **Binary Rejection**: Automatically detects and rejects binary files
- **Path Security**: Basic path validation and resolution
- **Error Isolation**: Errors in one file don't affect others

## Environment Support

### SWEBench Compatibility
When running in SWEBench (with `env` parameter):
- Uses efficient shell commands (`head`, `wc`, `test`)
- Works with `/testbed` paths in Docker containers
- Proper shell escaping for file paths
- Optimized for containerized execution

### Host Execution
When running on host filesystem (without `env` parameter):
- Direct Python file operations
- Path expansion and resolution
- Full Unicode support with error handling
- Detailed error reporting

## Implementation Details

### Architecture
The tool implements dual-mode execution:
1. **Environment Mode**: Uses shell commands via `env.execute()`
2. **Host Mode**: Direct filesystem operations using Python `pathlib`

### Security Considerations
- Path traversal protection through `pathlib` resolution
- File type validation to reject directories and special files
- Binary content detection to prevent processing non-text files
- Reasonable limits on file count and output size

### Error Recovery
- Continues processing remaining files when individual files fail
- Provides detailed error messages for each failure type
- Maintains summary statistics for batch operations

## Integration with mini-swe-agent

The tool is automatically registered in the global tool registry and available in:
- Interactive agent sessions
- SWEBench batch processing
- Custom agent configurations

### Registration
```python
from minisweagent.tools.read_many import ReadManyFilesTool
# Tool is automatically registered on import
```

## Limitations and Considerations

### Performance
- Maximum 20 files per call
- Default 50,000 character total limit
- Individual file line limits prevent excessive memory usage

### File Types
- Only UTF-8 text files are supported
- Binary files are automatically rejected
- Special files (devices, pipes) are not supported

### Memory Usage
- Content is loaded into memory for processing
- Large files are truncated to prevent memory issues
- Character limits provide hard caps on memory usage

## Future Enhancements

Potential improvements for future versions:
- Streaming processing for very large files
- Pattern-based file filtering
- Syntax-aware content extraction
- Incremental reading with pagination
- Custom output formats (XML, YAML, etc.)

## Troubleshooting

### Common Issues

**"Too many files requested"**
- Reduce the number of files to 20 or fewer
- Consider multiple calls for large file sets

**"Binary file detected"**
- Ensure all files are UTF-8 text files
- Remove binary files from the paths list

**Files showing as "skipped"**
- Check the `max_total_chars` limit
- Increase the limit or reduce the number of files

**Empty or truncated content**
- Check `max_lines_per_file` setting
- Verify `strip_empty_lines` behavior
- Review character limits

### Debug Tips
1. Start with `include_metadata: true` to see file sizes
2. Use smaller limits initially to test behavior
3. Check individual file permissions if errors occur
4. Test with single files first, then batch