from datetime import datetime


class TimeEngine:

    def get_time(self):
        return datetime.now().strftime("%I:%M %p")