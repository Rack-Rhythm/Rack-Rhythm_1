import json
import os

from google import genai
from google.genai import types


GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is not configured.")

client = genai.Client(api_key=GEMINI_API_KEY)


ALLOWED_CATEGORIES = [
    "Roads",
    "Water",
    "Sanitation",
    "Electricity",
    "Waste",
    "Traffic",
    "Parks",
]

ALLOWED_URGENCY = [
    "Critical",
    "High",
    "Moderate",
    "Low",
]


def analyze_civic_image(image_file):
    """
    Analyze an uploaded civic-issue image using Gemini.
    """

    image_bytes = image_file.read()

    mime_type = getattr(image_file, "content_type", None)

    if not mime_type:
        filename = getattr(image_file, "name", "").lower()

        if filename.endswith(".jfif") or filename.endswith(".jpg") or filename.endswith(".jpeg"):
          mime_type = "image/jpeg"
        elif filename.endswith(".png"):
          mime_type = "image/png"
        elif filename.endswith(".webp"):
         mime_type = "image/webp"
    else:
        mime_type = mime_type

    prompt = f"""
You are the computer vision system for JanSeva,
a civic grievance reporting platform.

Analyze the uploaded image and determine whether it
shows a genuine civic or municipal issue.

Allowed categories:
{", ".join(ALLOWED_CATEGORIES)}

Allowed urgency levels:
{", ".join(ALLOWED_URGENCY)}

Return ONLY valid JSON using exactly these fields:

{{
    "is_valid_civic_issue": true,
    "detected_issue": "short description",
    "category": "one allowed category",
    "confidence": 0.0,
    "severity": "Critical/High/Moderate/Low",
    "urgency": "Critical/High/Moderate/Low",
    "recommended_department": "municipal department",
    "suggested_sla_hours": 24,
    "description": "description of what is visible"
}}

Rules:

1. Only identify problems that are reasonably visible.
2. Do not invent damage or objects.
3. confidence must be between 0 and 1.
4. category must be one of the allowed categories.
5. urgency must be one of the allowed urgency levels.
6. severity must be one of the allowed urgency levels.
7. If there is no genuine civic issue, set
   is_valid_civic_issue to false.
8. suggested_sla_hours should reflect the urgency.
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=[
            types.Part.from_bytes(
                data=image_bytes,
                mime_type=mime_type,
            ),
            prompt,
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
        ),
    )

    result = json.loads(response.text)

    return validate_analysis(result)


def validate_analysis(result):
    """
    Validate Gemini's response before returning it
    to the Django API.
    """

    if not isinstance(result, dict):
        raise ValueError("Gemini returned an invalid response.")

    result["is_valid_civic_issue"] = bool(
        result.get("is_valid_civic_issue", False)
    )

    result["detected_issue"] = str(
        result.get("detected_issue", "Unknown civic issue")
    )

    if result.get("category") not in ALLOWED_CATEGORIES:
        result["category"] = "Roads"

    if result.get("urgency") not in ALLOWED_URGENCY:
        result["urgency"] = "Moderate"

    if result.get("severity") not in ALLOWED_URGENCY:
        result["severity"] = result["urgency"]

    try:
        result["confidence"] = float(
            result.get("confidence", 0)
        )
    except (TypeError, ValueError):
        result["confidence"] = 0.0

    result["confidence"] = max(
        0.0,
        min(1.0, result["confidence"])
    )

    try:
        result["suggested_sla_hours"] = int(
            result.get("suggested_sla_hours", 72)
        )
    except (TypeError, ValueError):
        result["suggested_sla_hours"] = 72

    result["recommended_department"] = str(
        result.get(
            "recommended_department",
            "Municipal Services"
        )
    )

    result["description"] = str(
        result.get("description", "")
    )

    return result