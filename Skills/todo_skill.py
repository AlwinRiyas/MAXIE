import os
import re
import json

from Config.config import Config


class TodoListSkill:
    """Personal to-do list stored as JSON.

    Supports: add, show, mark done, remove, clear. Done/remove match
    by task number, ordinal ("the second task"), or a text substring.
    Path is injectable for tests.
    """

    ORDINALS = {
        "first": 1, "second": 2, "third": 3, "fourth": 4,
        "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
        "ninth": 9, "tenth": 10,
    }

    def __init__(self, path=None):
        self.path = path or Config.resolve("Memory/todos.json")

    # ----------------------------------------------------------
    # Persistence
    # ----------------------------------------------------------

    def _load(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data = data.get("tasks", [])
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, tasks):
        directory = os.path.dirname(self.path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"tasks": tasks}, f, indent=2)

    # ----------------------------------------------------------
    # Public API
    # ----------------------------------------------------------

    def add(self, text):
        task = self._extract_item(text)
        if not task:
            return "What should I add to your list?"
        tasks = self._load()
        tasks.append({"id": self._next_id(tasks), "text": task, "done": False})
        self._save(tasks)
        return f"Added to your to-do list: {task}."

    def show(self, text=""):
        tasks = self._load()
        if not tasks:
            return "Your to-do list is empty."
        lines = ["Here's your to-do list:"]
        for task in tasks:
            mark = "[x]" if task["done"] else "[ ]"
            lines.append(f"{mark} {task['text']}")
        return "\n".join(lines)

    def done(self, text):
        tasks = self._load()
        if not tasks:
            return "Your to-do list is empty."
        if "all" in self._words(text):
            for task in tasks:
                task["done"] = True
            self._save(tasks)
            return "Everything on your list is done."
        targets = self._match_targets(tasks, text)
        if not targets:
            return "I couldn't find that task on your list."
        for task in tasks:
            if task["text"] in targets:
                task["done"] = True
        self._save(tasks)
        return self._format_names(targets, "Marked", "as done")

    def remove(self, text):
        tasks = self._load()
        if not tasks:
            return "Your to-do list is empty."
        if "all" in self._words(text):
            self._save([])
            return "Cleared your to-do list."
        targets = self._match_targets(tasks, text)
        if not targets:
            return "I couldn't find that task on your list."
        remaining = [t for t in tasks if t["text"] not in targets]
        self._save(remaining)
        return self._format_names(targets, "Removed", "from your list")

    def clear(self, text=""):
        self._save([])
        return "Cleared your to-do list."

    # ----------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------

    @staticmethod
    def _words(text):
        return set(text.lower().split())

    def _next_id(self, tasks):
        return max((t.get("id", 0) for t in tasks), default=0) + 1

    def _extract_item(self, text):
        item = text.lower().strip()

        for marker in ("to my todo list", "to my to-do list",
                       "to my task list", "to my list", "on my list",
                       "to the list", "to-do list", "to do list"):
            marker_ix = item.find(marker)
            if marker_ix != -1:
                item = item[:marker_ix].strip(" .")

        for prefix in ("add to my todo list ", "add to my to-do list ",
                       "add to my task list ", "add to my list ",
                       "add task ", "put on my list "):
            if item.startswith(prefix):
                return item[len(prefix):].strip(" .!?")

        for phrase in ("add ", "remind me to ", "remember to "):
            if item.startswith(phrase):
                return item[len(phrase):].strip(" .!?")

        return item.strip(" .!?")

    def _match_targets(self, tasks, text):
        lowered = text.lower()
        targets = []

        for match in re.findall(r"\b(\d+)\b", text):
            index = int(match) - 1
            if 0 <= index < len(tasks) and tasks[index]["text"] not in targets:
                targets.append(tasks[index]["text"])

        for ordinal, num in self.ORDINALS.items():
            if f"the {ordinal}" in lowered and num - 1 < len(tasks):
                text_of = tasks[num - 1]["text"]
                if text_of not in targets:
                    targets.append(text_of)

        for task in tasks:
            if task["text"].lower() and task["text"].lower() in lowered:
                if task["text"] not in targets:
                    targets.append(task["text"])

        return targets

    @staticmethod
    def _format_names(names, verb, tail):
        quoted = "', '".join(names[:5])
        more = f" and {len(names) - 5} more" if len(names) > 5 else ""
        return f"{verb} '{quoted}{more}' {tail}."