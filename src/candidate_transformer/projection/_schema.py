from ..models.config import FieldType, ProjectionConfig

_TYPE_MAP: dict[FieldType, str] = {
    FieldType.STRING: "string",
    FieldType.NUMBER: "number",
    FieldType.BOOLEAN: "boolean",
    FieldType.ARRAY: "array",
}


def derive_schema(config: ProjectionConfig) -> dict:
    """Build a JSON Schema dict from a ProjectionConfig.

    Rules:
    - Wildcard from_paths (containing '[]') always yield {type: "array"}.
    - required=True  → {type: X}     (null not permitted)
    - required=False → {type: [X, "null"]}  (null allowed, on_missing=null)
    - additionalProperties: True so _confidence / _provenance keys pass through.

    The schema is validated with jsonschema after every projection, so any
    mismatch between the config declaration and the actual output is surfaced
    as a clean ProjectionValidationError rather than a silent wrong value.
    """
    properties: dict = {}
    required_list: list[str] = []

    for spec in config.fields:
        if "[]" in spec.from_path:
            prop: dict = {"type": "array"}
        else:
            base = _TYPE_MAP.get(spec.type, "string")
            prop = {"type": base} if spec.required else {"type": [base, "null"]}

        properties[spec.path] = prop
        if spec.required:
            required_list.append(spec.path)

    schema: dict = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
        "properties": properties,
        "additionalProperties": True,   # allow metadata keys
    }
    if required_list:
        schema["required"] = required_list
    return schema
