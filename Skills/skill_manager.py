from Skills.open_app_skill import OpenAppSkill


class SkillManager:

    def __init__(self):

        self.open_app = OpenAppSkill()

    def execute(self, intent, data):

        if intent == "OPEN_APP":
            return self.open_app.execute(data)

        return "Skill not implemented yet."