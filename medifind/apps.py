from django.apps import AppConfig


class MediAIConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "medifind"

    def ready(self):
        import medifind.signals