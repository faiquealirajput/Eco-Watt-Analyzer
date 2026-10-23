import io
import json
import logging
import os
from typing import Any

from flask import Flask, jsonify, render_template, request
from google import genai
from google.genai import types
from PIL import Image, ImageOps, UnidentifiedImageError


logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024

TARIFF_PKR_PER_KWH = 55
MAX_IMAGE_PIXELS = 25_000_000
MODEL_NAME = "gemini-2.5-flash"

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "efficiency_score": {
            "type": "INTEGER",
            "description": "Room energy efficiency score from 0 to 100.",
        },
        "appliances": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "name": {"type": "STRING"},
                    "category": {"type": "STRING"},
                    "monthly_kwh": {"type": "NUMBER"},
                    "power_kw": {"type": "NUMBER"},
                    "daily_hours": {"type": "NUMBER"},
                    "status": {
                        "type": "STRING",
                        "enum": ["Critical", "Moderate", "Optimal"],
                    },
                    "solution": {
                        "type": "STRING",
                        "description": "One concise, practical energy-saving action.",
                    },
                    "is_heavy": {
                        "type": "BOOLEAN",
                        "description": "True for a major energy-consuming appliance.",
                    },
                },
                "required": [
                    "name",
                    "category",
                    "monthly_kwh",
                    "power_kw",
                    "daily_hours",
                    "status",
                    "solution",
                    "is_heavy",
                ],
            },
        },
        "optimization_directives": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "appliance": {"type": "STRING"},
                    "priority": {
                        "type": "STRING",
                        "enum": ["Critical", "Moderate", "Optimal"],
                    },
                    "action": {"type": "STRING"},
                },
                "required": ["appliance", "priority", "action"],
            },
        },
    },
    "required": ["efficiency_score", "appliances", "optimization_directives"],
}

FALLBACK_DATA = {
    "efficiency_score": 62,
    "appliances": [
        {
            "name": "Split AC",
            "category": "Cooling",
            "monthly_kwh": 390,
            "power_kw": 1.3,
            "daily_hours": 10,
            "status": "Critical",
            "solution": "Set the thermostat to 26°C and clean the air filter monthly.",
            "is_heavy": True,
        },
        {
            "name": "Refrigerator",
            "category": "Kitchen",
            "monthly_kwh": 85,
            "power_kw": 0.14,
            "daily_hours": 20,
            "status": "Moderate",
            "solution": "Leave space behind the fridge and check the door seal.",
            "is_heavy": True,
        },
        {
            "name": "Monitor",
            "category": "Workstation",
            "monthly_kwh": 54,
            "power_kw": 0.09,
            "daily_hours": 20,
            "status": "Moderate",
            "solution": "Enable auto-sleep and switch the display off when away.",
            "is_heavy": False,
        },
        {
            "name": "Ceiling fan",
            "category": "Cooling",
            "monthly_kwh": 48,
            "power_kw": 0.08,
            "daily_hours": 20,
            "status": "Optimal",
            "solution": "Use a BLDC fan to reduce power draw during long run times.",
            "is_heavy": False,
        },
        {
            "name": "LED lighting",
            "category": "Lighting",
            "monthly_kwh": 36,
            "power_kw": 0.06,
            "daily_hours": 20,
            "status": "Optimal",
            "solution": "Keep the LED fixtures and switch off unused zones.",
            "is_heavy": False,
        },
    ],
    "optimization_directives": [
        {
            "appliance": "Split AC",
            "priority": "Critical",
            "action": "Set 26°C, clean the filter monthly, and seal gaps around windows.",
        },
        {
            "appliance": "Refrigerator",
            "priority": "Moderate",
            "action": "Check the door gasket and allow airflow around the condenser.",
        },
        {
            "appliance": "Monitor",
            "priority": "Moderate",
            "action": "Enable auto-sleep and power down the display when not in use.",
        },
        {
            "appliance": "Ceiling fan",
            "priority": "Optimal",
            "action": "Consider a BLDC replacement at the next upgrade.",
        },
    ],
}


def _numeric(value: Any, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Expected a numeric value.")
    result = float(value)
    if not minimum <= result <= maximum:
        raise ValueError("Numeric value is outside the supported range.")
    return result


def normalize_analysis(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("The model response must be a JSON object.")
    score = int(_numeric(data.get("efficiency_score"), minimum=0, maximum=100))
    source_appliances = data.get("appliances")
    if not isinstance(source_appliances, list) or not source_appliances:
        raise ValueError("The model response did not include any appliances.")
    if len(source_appliances) > 30:
        raise ValueError("The model response included too many appliances.")

    appliances = []
    for item in source_appliances:
        if not isinstance(item, dict):
            raise ValueError("An appliance entry was not an object.")
        name = str(item.get("name", "")).strip()[:80]
        category = str(item.get("category", "Other")).strip()[:50]
        solution = str(item.get("solution", "")).strip()[:240]
        status = item.get("status")
        if not name or not solution or status not in ("Critical", "Moderate", "Optimal"):
            raise ValueError("An appliance entry is missing required information.")
        appliances.append(
            {
                "name": name,
                "category": category or "Other",
                "monthly_kwh": round(
                    _numeric(item.get("monthly_kwh"), minimum=0, maximum=100_000), 1
                ),
                "power_kw": round(
                    _numeric(item.get("power_kw"), minimum=0, maximum=100), 3
                ),
                "daily_hours": round(
                    _numeric(item.get("daily_hours"), minimum=0, maximum=24), 1
                ),
                "status": status,
                "solution": solution,
                "is_heavy": bool(item.get("is_heavy", False)),
            }
        )

    source_directives = data.get("optimization_directives", [])
    if not isinstance(source_directives, list) or len(source_directives) > 30:
        raise ValueError("The model returned invalid optimization directives.")
    directives = []
    for item in source_directives:
        if not isinstance(item, dict):
            raise ValueError("An optimization directive was not an object.")
        appliance = str(item.get("appliance", "")).strip()[:80]
        action = str(item.get("action", "")).strip()[:240]
        priority = item.get("priority")
        if (
            not appliance
            or not action
            or priority not in ("Critical", "Moderate", "Optimal")
        ):
            raise ValueError("An optimization directive is incomplete.")
        directives.append(
            {"appliance": appliance, "priority": priority, "action": action}
        )

    total_kwh = round(sum(item["monthly_kwh"] for item in appliances), 1)
    return {
        "efficiency_score": score,
        "appliances": appliances,
        "optimization_directives": directives,
        "total_monthly_kwh": total_kwh,
        "monthly_bill_pkr": round(total_kwh * TARIFF_PKR_PER_KWH),
        "tariff_pkr_per_kwh": TARIFF_PKR_PER_KWH,
        "source": "gemini",
        "notice": None,
    }


def fallback_analysis(notice: str) -> dict[str, Any]:
    result = normalize_analysis(FALLBACK_DATA)
    result["source"] = "fallback"
    result["notice"] = notice
    return result


def prepare_image(upload: Any) -> tuple[bytes, str]:
    raw = upload.read()
    if not raw:
        raise ValueError("The uploaded image is empty.")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in ("JPEG", "PNG", "WEBP"):
                raise ValueError("Use a JPEG, PNG, or WebP image.")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("The image is too large to analyze.")
            image.load()
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA"):
                background = Image.new("RGB", image.size, "white")
                background.paste(image, mask=image.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=88, optimize=True)
            return output.getvalue(), "image/jpeg"
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("The uploaded file is not a valid supported image.") from exc


def analyze_with_gemini(image_bytes: bytes, mime_type: str) -> dict[str, Any]:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY is not configured; using demo analysis.")
        return fallback_analysis(
            "Demo analysis is active because GEMINI_API_KEY is not configured."
        )

    prompt = (
        "Analyze this room or office photo as an energy auditor. Identify only "
        "electrical appliances that are visibly present; do not invent hidden devices. "
        "Estimate each visible appliance's monthly electricity use in kWh for a typical "
        "Pakistan household, its operating power in kW, and typical hours used per day. "
        "Use plausible estimates, not measurements. Set is_heavy true for major loads "
        "such as air conditioners, water heaters, or refrigerators. Rate efficiency "
        "from 0 (very inefficient) to 100 (highly efficient), based on visible evidence. "
        "For every appliance give a concise actionable saving solution and status "
        "(Critical, Moderate, or Optimal). Give up to five matching concise optimization "
        "directives. If no appliances can be identified, return one entry named "
        "'No visible appliances' with zero energy use and an explanation in its solution."
    )
    try:
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=30_000),
        )
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESPONSE_SCHEMA,
                temperature=0.2,
            ),
        )
        if not response.text:
            raise ValueError("Gemini returned an empty response.")
        return normalize_analysis(json.loads(response.text))
    except Exception:
        logger.exception("Gemini analysis failed; returning demo analysis.")
        return fallback_analysis(
            "Live analysis is temporarily unavailable. Showing a realistic demo estimate."
        )


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/analyze")
def analyze():
    upload = request.files.get("image")
    if upload is None:
        return jsonify({"error": "Choose a room photo before starting the scan."}), 400
    try:
        image_bytes, mime_type = prepare_image(upload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(analyze_with_gemini(image_bytes, mime_type))


@app.errorhandler(413)
def request_too_large(_error):
    return jsonify({"error": "Image exceeds the 10 MB upload limit."}), 413


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "").lower() == "true",
    )
