import json
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

import requests


# -------------------------------------------------
# STEP 1: Get evening weather for Orange, CA
# -------------------------------------------------
def get_evening_weather(location: str, api_key: str) -> dict:
    """
    Pulls OpenWeather 5-day / 3-hour forecast and selects
    an approximate evening forecast for decision-making.
    """
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {
        "q": location,
        "appid": api_key,
        "units": "imperial",
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    chosen = None

    # Heuristic: pick a UTC time between 00–07 (often evening PT)
    for item in data.get("list", []):
        dt_txt = item.get("dt_txt", "")
        if len(dt_txt) >= 13:
            utc_hour = int(dt_txt[11:13])
            if 0 <= utc_hour <= 7:
                chosen = item
                break

    if not chosen:
        chosen = data["list"][0]

    main = chosen.get("main", {})
    weather = (chosen.get("weather") or [{}])[0]
    wind = chosen.get("wind", {})

    return {
        "location": location,
        "forecast_time_utc": chosen.get("dt_txt"),
        "temp_f": main.get("temp"),
        "feels_like_f": main.get("feels_like"),
        "humidity_pct": main.get("humidity"),
        "conditions": weather.get("description"),
        "wind_mph": wind.get("speed"),
    }


# -------------------------------------------------
# STEP 2: Ask AI to create the Jain menu (STRICT)
# -------------------------------------------------
def generate_jain_menu(weather: dict) -> dict:
    api_key = os.environ["OPENAI_API_KEY"]

    system_prompt = (
        "You are a professional Indian home chef specializing in HEALTHY Jain vegetarian cooking.\n"
        "STRICT RULES:\n"
        "- Vegetarian only.\n"
        "- NO onion, NO garlic.\n"
        "- Avoid root vegetables: potato, carrot, beet, radish, sweet potato, yam.\n"
        "- Use hing, ginger, tomatoes, herbs, spices for flavor.\n"
        "- Healthy bias: steaming, simmering, roasting, light sautéing.\n"
        "- Avoid deep frying.\n"
        "- Moderate sugar; desserts should be lighter in hot weather.\n"
        "- Recipes must be realistic, cookable, and weeknight-appropriate.\n"
        "- Tone: polished, professional, cookbook-quality.\n"
        "- Do NOT mention AI, disclaimers, or substitutions unless required for Jain compliance."
    )

    user_prompt = f"""
Evening weather for Orange, California:
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
- No prohibited ingredients.
- Clear steps.
- Common household measurements.
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
            ],
            "text": {"format": {"type": "json_object"}},
        },
        timeout=60,
    )

    response.raise_for_status()
    output = response.json()
    text = output["output"][0]["content"][0]["text"]

    return json.loads(text)


# -------------------------------------------------
# STEP 3: Send email
# -------------------------------------------------
def send_email(subject: str, body: str):
    email_from = os.environ["EMAIL_FROM"]
    email_to = [e.strip() for e in os.environ["EMAIL_TO"].split(",") if e.strip()]
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]

    msg = EmailMessage()
    msg["From"] = email_from
    msg["To"] = ", ".join(email_to)
    msg["Subject"] = subject
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


# -------------------------------------------------
# STEP 4: Format email body
# -------------------------------------------------
def format_email(weather: dict, menu: dict) -> str:
    def section(title):
        return f"\n{'=' * len(title)}\n{title}\n{'=' * len(title)}\n"

    lines = []
    lines.append(menu["title"])
    lines.append("")
    lines.append("Weather (Evening):")
    lines.append(f"- Temp: {weather['temp_f']}°F (feels {weather['feels_like_f']}°F)")
    lines.append(f"- Conditions: {weather['conditions']}")
    lines.append(f"- Wind: {weather['wind_mph']} mph | Humidity: {weather['humidity_pct']}%")
    lines.append("")
    lines.append(menu["weather_fit_summary"])

    a = menu["menu"]["appetizer"]
    lines.append(section("APPETIZER"))
    lines.append(f"{a['name']} ({a['time_minutes']} min)")
    lines.append("Ingredients:")
    for i in a["ingredients"]:
        lines.append(f"- {i}")
    lines.append("Steps:")
    for s in a["steps"]:
        lines.append(f"- {s}")

    m = menu["menu"]["main"]
    lines.append(section("MAIN"))
    lines.append(f"{m['name']} ({m['time_minutes']} min)")
    lines.append("Ingredients:")
    for i in m["ingredients"]:
        lines.append(f"- {i}")
    lines.append("Steps:")
    for s in m["steps"]:
        lines.append(f"- {s}")

    side = m.get("side")
    if side:
        lines.append("\nSide:")
        lines.append(f"{side['name']} ({side['time_minutes']} min)")
        for s in side["steps"]:
            lines.append(f"- {s}")

    d = menu["menu"]["dessert"]
    lines.append(section("DESSERT"))
    lines.append(f"{d['name']} ({d['time_minutes']} min)")
    for s in d["steps"]:
        lines.append(f"- {s}")

    lines.append(section("SHOPPING LIST"))
    for cat, items in menu["shopping_list"].items():
        lines.append(f"{cat.capitalize()}:")
        for i in items:
            lines.append(f"- {i}")

    lines.append(section("JAIN COMPLIANCE"))
    for n in menu["jain_compliance_notes"]:
        lines.append(f"- {n}")

    return "\n".join(lines)


# -------------------------------------------------
# STEP 5: Run everything
# -------------------------------------------------
def main():
    location = os.environ.get("LOCATION", "Orange,CA,US")
    weather = get_evening_weather(location, os.environ["OPENWEATHER_API_KEY"])
    menu = generate_jain_menu(weather)

    subject = f"Healthy Jain Dinner – {datetime.now().strftime('%A, %B %d')}"
    body = format_email(weather, menu)

    send_email(subject, body)
    print("Email sent successfully.")


if __name__ == "__main__":
    main()
