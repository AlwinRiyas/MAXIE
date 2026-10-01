import requests

from Config.config import Config

DEFAULT_CITY = "Chennai"
DEFAULT_COORDS = (13.0827, 80.2707)


class WeatherConfig:
    """Resolve location settings for the WeatherEngine.

    Reads 'weather' section from system_config.json:

        "weather": {
            "city": "Chennai",
            "latitude": null,
            "longitude": null
        }

    If no city/coords are configured, defaults to the project default
    (Chennai) so MAXIE still works out of the box.
    """

    @classmethod
    def get_location(cls):
        system = Config.system()
        weather = system.get("weather", {})

        city = weather.get("city") or DEFAULT_CITY
        lat = weather.get("latitude")
        lon = weather.get("longitude")

        if lat is None or lon is None:
            lat, lon = cls._geocode(city)
            if lat is None or lon is None:
                return (*DEFAULT_COORDS, city)

        return float(lat), float(lon), city

    @classmethod
    def _geocode(cls, city):
        try:
            response = requests.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "en"},
                timeout=8,
            )
            response.raise_for_status()
            data = response.json()
            results = data.get("results") or []
            if not results:
                return None, None
            return results[0]["latitude"], results[0]["longitude"]
        except (requests.RequestException, OSError, ValueError, KeyError):
            return None, None