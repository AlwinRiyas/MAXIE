import requests

from Weather.weather_config import WeatherConfig

# WMO weather interpretation codes -> short human description.
WMO = {
    0: "clear",
    1: "mostly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "foggy with icy fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "heavy freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    80: "light rain showers",
    81: "rain showers",
    82: "violent rain showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "thunderstorms with heavy hail",
}

BASE = "https://api.open-meteo.com/v1/forecast"
GEO = "https://geocoding-api.open-meteo.com/v1/search"


class WeatherEngine:
    """Weather via open-meteo (free, no API key).

    Location is configurable (city name + optional coordinates in
    Config/audio... no: Config/system_config.json -> 'weather'), with a
    sensible default. Fails gracefully when offline.
    """

    def get_weather(self):
        lat, lon, city = WeatherConfig.get_location()

        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code,wind_speed_10m",
            "timezone": "auto",
        }

        try:
            response = requests.get(BASE, params=params, timeout=12)
            response.raise_for_status()
            data = response.json()
        except (requests.RequestException, OSError, ValueError) as error:
            return f"Weather isn't available right now: {error}"

        try:
            current = data["current"]
            temp = current["temperature_2m"]
            code = current.get("weather_code", 0)
            wind = current.get("wind_speed_10m", 0)
        except (KeyError, TypeError, ValueError):
            return "I couldn't parse the weather data."

        condition = WMO.get(int(code), "unknown conditions")

        location = f"in {city}" if city else ""
        text = (
            f"The current temperature {location} is {temp:.0f}°C, "
            f"{condition}, with wind around {wind:.0f} km/h."
        )
        return text