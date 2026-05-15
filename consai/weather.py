import logging
import requests
from consai.config import OPENWEATHER_API_KEY
from consai.utils import get_location

logger = logging.getLogger(__name__)

# ── Defaults ──────────────────────────────────────────────────────────────────

EMPTY_WEATHER = {
    "weather_temp":     None,
    "weather_desc":     None,
    "weather_humidity": None,
}

# ── Main ──────────────────────────────────────────────────────────────────────

def get_weather(lat: float = None, lon: float = None) -> dict:
    """
    Fetch current weather for given coordinates.
    Falls back to IP-based location if lat/lon not provided.
    Returns empty weather dict if API key missing or request fails.
    """
    if not OPENWEATHER_API_KEY:
        logger.warning("OPENWEATHER_API_KEY not set — skipping weather")
        return EMPTY_WEATHER

    # Use provided coords or fall back to IP location
    if lat is None or lon is None:
        location = get_location()
        lat = location["lat"]
        lon = location["lon"]

    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "lat":   lat,
                "lon":   lon,
                "appid": OPENWEATHER_API_KEY,
                "units": "metric",
            },
            timeout=8,
        )
        r.raise_for_status()
        data = r.json()

        return {
            "weather_temp":     round(data["main"]["temp"], 1),
            "weather_desc":     data["weather"][0]["description"],
            "weather_humidity": data["main"]["humidity"],
        }

    except requests.exceptions.Timeout:
        logger.warning("Weather request timed out")
        return EMPTY_WEATHER
    except requests.exceptions.HTTPError as e:
        logger.warning(f"Weather API error: {e}")
        return EMPTY_WEATHER
    except Exception as e:
        logger.warning(f"Weather fetch failed: {e}")
        return EMPTY_WEATHER


if __name__ == "__main__":
    from consai.utils import get_location

    loc = get_location()
    print(f"📍 Location: {loc['location_name']} ({loc['lat']}, {loc['lon']})")

    weather = get_weather(loc["lat"], loc["lon"])
    print(f"🌤  Weather: {weather}")