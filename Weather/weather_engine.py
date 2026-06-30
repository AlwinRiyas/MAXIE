import requests


class WeatherEngine:

    def get_weather(self):

        url = (
            "https://api.open-meteo.com/v1/forecast"
            "?latitude=13.0827"
            "&longitude=80.2707"
            "&current=temperature_2m,weather_code"
        )

        response = requests.get(url)

        data = response.json()

        temperature = data["current"]["temperature_2m"]

        return f"{temperature}°C"