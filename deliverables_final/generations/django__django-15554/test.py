{
    "name": "replace",
    "args": {
        "path": "patch_query_class.py",
        "old_text": """                    resolved_value = value.resolve_expression(compiler.query)\\\
                    value_sql, value_params = compiler.compile(resolved_value)\\\
                    sql_parts.append(f"{compiler.quote_name_unless_alias(key)} = {value_sql}")\\\
                    params.extend(value_params)""",
        "new_text": """                    resolved_value = value.resolve_expression(compiler.query)
                    value_sql, value_params = compiler.compile(resolved_value)
                    sql_parts.append(f"{compiler.quote_name_unless_alias(key)} = {value_sql}")
                    params.extend(value_params)""",
    },
}
