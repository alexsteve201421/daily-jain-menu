import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import requests


# -------------------------------------------------
# Weather A: CURRENT weather at send time
# -------------------------------------------------
def get_current_weather(location: str, api_key: str) -> dict:
    """
    Gets current weather (now) for the location.
    Uses OpenWeather Current Weather endpoint.
    """
    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {"q": location, "appid": api_key, "units": "imperial"}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    tz_offset_seconds = int(data.get("timezone", 0))
    tz = timezone(timedelta(seconds=tz_offset_seconds))

    # OpenWeather gives dt (UTC timestamp of observation)
    dt_utc = datetime.fromtimestamp(int(data.get("dt", 0)), tz=timezone.utc)
    dt_local = dt_utc.astimezone(tz)

    main = data.get("main", {})
    w = (data.get("weather") or [{}])[0]
    wind = data.get("wind", {})

    return {
        "location": location,
        "observed_time_local": dt_local.strftime("%Y-%m-%d %I:%M %p"),
        "temp_f": main.get("temp"),
        "feels_like_f": main.get("feels_like"),
        "humidity_pct": main.get("humidity"),
        "conditions": w.get("description"),
        "wind_mph": wind.get("speed"),
    }


# -------------------------------------------------
# Weather B: DINNER forecast closest to 7:00 PM local time
# -------------------------------------------------
def get_dinner_forecast(location: str, api_key: str, dinner_hour_local: int = 19) -> dict:
    """
    Uses OpenWeather 5-day/3-hour forecast and selects the entry closest
    to dinner time (default 7:00 PM) in the city's local time.
    DST is handled via OpenWeather's city timezone offset.
    """
    url = "https://api.openweathermap.org/data/2.5/forecast"
    params = {"q": location, "appid": api_key, "units": "imperial"}

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    city = data.get("city", {})
    tz_offset_seconds = int(city.get("timezone", 0))
    tz = timezone(timedelta(seconds=tz_offset_seconds))

    now_local = datetime.now(tz)

    # Target is the NEXT occurrence of 7:00 PM local time
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
        "dinner_hour_local": dinner_hour_local,
        "forecast_time_local": chosen_local.strftime("%Y-%m-%d %I:%M %p"),
        "temp_f": main.get("temp"),
        "feels_like_f": main.get("feels_like"),
        "humidity_pct": main.get("humidity"),
        "conditions": w.get("description"),
        "wind_mph": wind.get("speed"),
    }


# -------------------------------------------------
# OpenAI: generate HEALTHY Jain menu (STRICT JSON)
# -------------------------------------------------
def generate_jain_menu(dinner_forecast: dict) -> dict:
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
The menu MUST be based on the DINNER-TIME FORECAST (around 7:00 PM local), not the current weather.

Dinner-time forecast for {dinner_forecast["location"]}:
{json.dumps(dinner_forecast, indent=2)}

Create a COMPLETE Indian Jain dinner menu with:
• 1 Appetizer
• 1 Main (include a simple side if appropriate)
• 1 Dessert

Make the menu fit the dinner-time forecast:
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

Rules:
- Absolutely no onion, no garlic, no root vegetables.
- Keep steps clear, specific, and cookable.
- Use common household measurements (cups/tbsp/tsp).
- Professional tone only.
"""

    resp = requests.post(
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
    resp.raise_for_status()
    data = resp.json()

    text = data["output"][0]["content"][0]["text"]
    return json.loads(text)


# -------------------------------------------------
# Email
# -------------------------------------------------
def send_email(subject: str, body: str) -> None:
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


def format_email(current_weather: dict, dinner_forecast: dict, menu: dict) -> str:
    def section(title: str) -> str:
        return f"\n{'=' * len(title)}\n{title}\n{'=' * len(title)}\n"

    lines = []
    lines.append(menu.get("title", "Tonight’s Healthy Jain Menu"))
    lines.append("")
    lines.append("Menu logic:")
    lines.append("- The MENU is based on the DINNER-TIME FORECAST (around 7:00 PM local).")
    lines.append("- The CURRENT WEATHER below is shown only for reference at send-time.")
    lines.append("")

    # CURRENT weather block (send-time)
    lines.append(section("CURRENT WEATHER (AT SEND TIME)"))
    lines.append(f"- Location: {current_weather.get('location')}")
    lines.append(f"- Observed (local): {current_weather.get('observed_time_local')}")
    lines.append(f"- Temp: {current_weather.get('temp_f')}°F (feels {current_weather.get('feels_like_f')}°F)")
    lines.append(f"- Conditions: {current_weather.get('conditions')}")
    lines.append(f"- Wind: {current_weather.get('wind_mph')} mph | Humidity: {current_weather.get('humidity_pct')}%")

    # DINNER forecast block (menu is based on this)
    lines.append(section("DINNER FORECAST (MENU IS BASED ON THIS)"))
    lines.append(f"- Target: ~{dinner_forecast.get('dinner_hour_local')}:00 local")
    lines.append(f"- Forecast time (local): {dinner_forecast.get('forecast_time_local')}")
    lines.append(f"- Temp: {dinner_forecast.get('temp_f')}°F (feels {dinner_forecast.get('feels_like_f')}°F)")
    lines.append(f"- Conditions: {dinner_forecast.get('conditions')}")
    lines.append(f"- Wind: {dinner_forecast.get('wind_mph')} mph | Humidity: {dinner_forecast.get('humidity_pct')}%")
    lines.append("")
    lines.append(menu.get("weather_fit_summary", ""))

    # Appetizer
    a = menu["menu"]["appetizer"]
    lines.append(section("APPETIZER"))
    lines.append(f"{a['name']}  •  {a['time_minutes']} min  •  Serves {a['servings']}")
    lines.append("\nIngredients:")
    for i in a["ingredients"]:
        lines.append(f"- {i}")
    lines.append("\nSteps:")
    for idx, s in enumerate(a["steps"], 1):
        lines.append(f"{idx}. {s}")
    if a.get("plating_note"):
        lines.append(f"\nPlating note: {a['plating_note']}")

    # Main + side
    m = menu["menu"]["main"]
    lines.append(section("MAIN"))
    lines.append(f"{m['name']}  •  {m['time_minutes']} min  •  Serves {m['servings']}")
    lines.append("\nIngredients:")
    for i in m["ingredients"]:
        lines.append(f"- {i}")
    lines.append("\nSteps:")
    for idx, s in enumerate(m["steps"], 1):
        lines.append(f"{idx}. {s}")

    side = m.get("side")
    if side and side.get("name"):
        lines.append("\nSide:")
        lines.append(f"{side['name']}  •  {side.get('time_minutes', '?')} min")
        lines.append("Ingredients:")
        for i in side.get("ingredients", []):
            lines.append(f"- {i}")
        lines.append("Steps:")
        for idx, s in enumerate(side.get("steps", []), 1):
            lines.append(f"{idx}. {s}")

    if m.get("plating_note"):
        lines.append(f"\nPlating note: {m['plating_note']}")

    # Dessert
    d = menu["menu"]["dessert"]
    lines.append(section("DESSERT"))
    lines.append(f"{d['name']}  •  {d['time_minutes']} min  •  Serves {d['servings']}")
    lines.append("\nIngredients:")
    for i in d["ingredients"]:
        lines.append(f"- {i}")
    lines.append("\nSteps:")
    for idx, s in enumerate(d["steps"], 1):
        lines.append(f"{idx}. {s}")
    if d.get("plating_note"):
        lines.append(f"\nPlating note: {d['plating_note']}")

    # Shopping list
    lines.append(section("SHOPPING LIST"))
    shopping = menu.get("shopping_list", {})
    for cat in ["produce", "pantry", "dairy", "spices"]:
        items = shopping.get(cat, [])
        if items:
            lines.append(f"{cat.capitalize()}:")
            for x in items:
                lines.append(f"- {x}")
            lines.append("")

    # Jain notes
    notes = menu.get("jain_compliance_notes", [])
    if notes:
        lines.append(section("JAIN COMPLIANCE"))
        for n in notes:
            lines.append(f"- {n}")

    return "\n".join(lines)


def main():
    # Default to Baltimore. Override with LOCATION secret if you want.
    location = os.environ.get("LOCATION", "Baltimore,MD,US")
    ow_key = os.environ["OPENWEATHER_API_KEY"]

    # Weather shown in email: NOW
    current_weather = get_current_weather(location, ow_key)

    # Weather used for menu: dinner-time forecast near 7 PM
    dinner_forecast = get_dinner_forecast(location, ow_key, dinner_hour_local=19)

    menu = generate_jain_menu(dinner_forecast)

    subject = f"Healthy Jain Dinner Plan – {datetime.now().strftime('%A, %B %d')} (Menu based on 7PM forecast)"
    body = format_email(current_weather, dinner_forecast, menu)

    send_email(subject, body)
    print("Email sent successfully.")


if __name__ == "__main__":
    main()
