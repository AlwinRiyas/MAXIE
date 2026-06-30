from datetime import datetime


class DateEngine:

    def get_today(self):
        return datetime.now().strftime("%A, %d %B %Y")