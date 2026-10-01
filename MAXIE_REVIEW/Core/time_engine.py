from datetime import datetime


class TimeEngine:

    def get_time(self):
        return datetime.now().strftime("%I:%M %p")

    def get_time_response(self):
        return f"The time is {self.get_time()}."

    def get_hour(self):
        return datetime.now().hour