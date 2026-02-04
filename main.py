import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import requests


# -------------------------------------------------
# STEP 1: Get dinner-time weather (closest to 7:00 PM local time)
# -------------------------------------------------
def get_dinner_weather(location: str, api_key: str, dinner_hour_local: int = 19) -> dict:
    """
    Uses OpenWeather 5-day/3-hour forecast and selects the forecast entry closest
    to dinner time (default 7:00 PM) in the CITY'S local time.
    DST is handled via OpenWeather city timezone offset (seconds from UTC).
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
# STEP 2: OpenAI generates a HEALTHY Jain menu (STRICT JSON)
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

Make the menu fit the weather:
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
# STEP 3: Email send (Gmail SMTP)
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


# -------------------------------------------------
# STEP 4: Email formatting (professional)
# -------------------------------------------------
def format_email(weather: dict, menu: dict) -> str:
    def section(title: str) -> str:
        return f"\n{'=' * len(title)}\n{title}\n{'=' * len(title)}\n"

    lines = []
    lines.append(menu.get("title", "Tonight’s Healthy Jain Menu"))
    lines.append("")
    lines.append("Dinner-time Weather:")
    lines.append(f"- Location: {weather.get('location')}")
    lines.append(f"- Forecast (local): {weather.get('forecast_time_local')}")
    lines.append(f"- Temp: {weather.get('temp_f')}°F (feels {weather.get('feels_like_f')}°F)")
    lines.append(f"- Conditions: {weather.get('conditions')}")
    lines.append(f"- Wind: {weather.get('wind_mph')} mph | Humidity: {weather.get('humidity_pct')}%")
    lines.append("")
    lines.append(menu.get("weather_fit_summary", ""))

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

    lines.append(section("SHOPPING LIST"))
    shopping = menu.get("shopping_list", {})
    for cat in ["produce", "pantry", "dairy", "spices"]:
        items = shopping.get(cat, [])
        if items:
            lines.append(f"{cat.capitalize()}:")
            for x in items:
                lines.append(f"- {x}")
            lines.append("")

    notes = menu.get("jain_compliance_notes", [])
    if notes:
        lines.append(section("JAIN COMPLIANCE"))
        for n in notes:
            lines.append(f"- {n}")

    return "\n".join(lines)


# -------------------------------------------------
# STEP 5: Main
# -------------------------------------------------
def main():
    # Default location is Baltimore, MD, US — override by setting LOCATION secret
    location = os.environ.get("LOCATION", "Baltimore,MD,US")

    weather = get_dinner_weather(
        location=location,
        api_key=os.environ["OPENWEATHER_API_KEY"],
        dinner_hour_local=19,  # 7 PM local
    )

    menu = generate_jain_menu(weather)

    subject = f"Healthy Jain Dinner Plan – {datetime.now().strftime('%A, %B %d')}"
    body = format_email(weather, menu)

    send_email(subject, body)
    print("Email sent successfully.")


if __name__ == "__main__":
    main()
