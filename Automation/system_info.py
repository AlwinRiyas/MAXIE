import os
import platform
import socket
import getpass
import psutil


class SystemInfo:

    def get_system_info(self):

        battery = psutil.sensors_battery()

        return {

            "OS": platform.system(),

            "OS Version": platform.release(),

            "Computer Name": socket.gethostname(),

            "Current User": getpass.getuser(),

            "CPU Usage": f"{psutil.cpu_percent(interval=1)}%",

            "RAM Usage": f"{psutil.virtual_memory().percent}%",

            "Available RAM": f"{round(psutil.virtual_memory().available / (1024**3),2)} GB",

            "Disk Usage": f"{psutil.disk_usage('/').percent}%",

            "Battery":
            f"{battery.percent}%"
            if battery
            else "Not Available"

        }