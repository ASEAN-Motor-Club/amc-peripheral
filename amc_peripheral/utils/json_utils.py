import json
from io import BytesIO
from typing import List

def convert_to_json_bytes(race_data: List) -> BytesIO:
    # Handle Pydantic models if present
    data = [p.model_dump() if hasattr(p, 'model_dump') else p for p in race_data]
    json_string = json.dumps(data, indent=2)
    return BytesIO(json_string.encode('utf-8'))
