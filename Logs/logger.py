import logging
import os


class Logger:

    def __init__(self):

        if not os.path.exists("Logs"):
            os.makedirs("Logs")

        logging.basicConfig(
            filename="Logs/maxie.log",
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(message)s"
        )

    def info(self, message):
        logging.info(message)

    def warning(self, message):
        logging.warning(message)

    def error(self, message):
        logging.error(message)