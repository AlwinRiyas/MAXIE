from datetime import datetime


class DateEngine:

    def get_today(self):
        return datetime.now().strftime("%A, %d %B %Y")

    # Backward-compatible alias (previously missing -> skill crash bug).
    def get_date(self):
        return self.get_today()

    def get_date_response(self):
        return f"Today is {self.get_today()}."

    def get_weekday(self):
        return datetime.now().strftime("%A")