from dataclasses import dataclass


@dataclass
class PromptTemplate:
    template: str = ""


class PromptRegistry:
    def register(self, name, template):
        pass

    def get(self, name):
        return PromptTemplate()
