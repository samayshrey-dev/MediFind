from django.apps import AppConfig


class MedifindConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "medifind"

    def ready(self):
        import medifind.signals