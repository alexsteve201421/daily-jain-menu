import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import requests


# -------------------------------------------------
# STEP 1: Get dinner-time weather (closest to 7:00 PM local)
# -------------------------------------------------
def get_dinner_weather(location: str, api_key: str, dinner_hour_local: int = 19) -> dict:
    """
    Pull OpenWeather 5-day/3-hour forecast and choose the entry closest to 7:00 PM LOCAL time
    for the forecast city (handles DST via OpenWeather timezone offset).
    """
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {"q": location, "appid": api_key, "units": "imperial"}

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    city = data.get("city", {})
    tz_offset_seconds = int(city.get("timezone", 0))  # seconds offset from UTC
    tz = timezone(timedelta(seconds=tz_offset_seconds))

    now_local = datetime.now(tz)
    target_local = now_local.replace(hour=dinner_hour_local, minute=0, second=0, microsecond=0)
    if now_local >= target_local:
        target_local = target_local + timedelta(days=1)

    best_item = None
    best_delta = None

    for item in data.get("list", []):
        dt_utc = datetime.fromtimestamp(int(item["dt"]), tz=timezone.utc)
        dt_local = dt_utc.astimezone(tz)
        delta = abs((dt_local - target_local).total_seconds())
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_item = item

    chosen = best_item if best_item else data["list"][0]

    main = chosen.get("main", {})
    w = (chosen.get("weather") or [{}])[0]
    wind = chosen.get("wind", {})

    chosen_utc = datetime.fromtimestamp(int(chosen["dt"]), tz=timezone.utc)
    chosen_local = chosen_utc.astimezone(tz)

    return {
        "location": location,
        "forecast_time_local": chosen_local.strftime("%Y-%m-%d %I:%M %p"),
        "forecast_time_utc": chosen_utc.strftime("%Y-%m-%d %H:%M:%S"),
        "temp_f": main.get("temp"),
        "feels_like_f": main.get("feels_like"),
        "humidity_pct": main.get("humidity"),
        "conditions": w.get("description"),
        "wind_mph": wind.get("speed"),
        "tz_offset_seconds": tz_offset_seconds,
        "dinner_hour_local": dinner_hour_local,
    }


# -------------------------------------------------
# STEP 2: Ask AI to create the Jain menu (STRICT JSON)
# -------------------------------------------------
def generate_jain_menu(weather: dict) -> dict:
    api_key = os.environ["OPENAI_API_KEY"]

    system_prompt = (
        "You are a professional Indian home chef specializing in HEALTHY Jain vegetarian cooking.\n"
        "STRICT RULES (must follow):\n"
        "- Vegetarian only.\n"
        "- NO onion, NO garlic.\n"
        "- Avoid root vegetables: potato, carrot, beet, radish, sweet potato, yam, etc.\n"
        "- Use hing (asafoetida), ginger, tomatoes, herbs, and spices for flavor depth.\n"
        "- Healthy bias: steaming, simmering, roasting, light sautéing.\n"
        "- Avoid deep frying.\n"
        "- Moderate oil and sugar; desserts should be lighter when hot/humid.\n"
        "- Recipes must be realistic, cookable, and weeknight-appropriate.\n"
        "- Tone: polished, professional, cookbook-quality.\n"
        "- Do NOT mention AI, disclaimers, or long preambles."
    )

    user_prompt = f"""
Dinner-time weather for {weather["location"]} (closest forecast to {weather["dinner_hour_local"]}:00 local):
{json.dumps(weather, indent=2)}

Create a COMPLETE Indian Jain dinner menu with:
• 1 Appetizer
• 1 Main (include a simple side if appropriate)
• 1 Dessert

Adjust the menu to the weather:
- Cold / windy / rainy → warm, comforting foods
- Hot / humid → lighter, cooling foods
- Mild → balanced, healthy meal

Return STRICT JSON ONLY in this exact structure:

{{
  "title": "string",
  "weather_fit_summary": "string",
  "menu": {{
    "appetizer": {{
      "name": "string",
      "time_minutes": integer,
      "servings": integer,
      "ingredients": ["string"],
      "steps": ["string"],
      "plating_note": "string"
    }},
    "main": {{
      "name": "string",
      "time_minutes": integer,
      "servings": integer,
      "ingredients": ["string"],
      "steps": ["string"],
      "side": {{
        "name": "string",
        "time_minutes": integer,
        "ingredients": ["string"],
        "steps": ["string"]
      }},
      "plating_note": "string"
    }},
    "dessert": {{
      "name": "string",
      "time_minutes": integer,
      "servings": integer,
      "ingredients": ["string"],
      "steps": ["string"],
      "plating_note": "string"
    }}
  }},
  "shopping_list": {{
    "produce": ["string"],
    "pantry": ["string"],
    "dairy": ["string"],
    "spices": ["string"]
  }},
  "jain_compliance_notes": ["string"]
}}

RULES:
- No onion, no garlic, no root vegetables.
- Keep steps clear, specific, and cookable.
- Use common household measurements (cups/tbsp/tsp).
- Keep it healthy and weeknight-realistic.
- Professional tone only.
"""

    response = requests.post(
        "https://api.openai.com/v1/responses",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": "gpt-4.1-mini",
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
 
::contentReference[oaicite:0]{index=0}
