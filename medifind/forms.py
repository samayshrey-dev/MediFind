from django import forms
from django.contrib.auth.models import User
from .models import Medicine, Pharmacy, Inventory, UserProfile


class BootstrapFormMixin:
    """Mixin to apply Bootstrap form-control / form-select styling automatically to form fields."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "form-check-input"
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                existing_class = widget.attrs.get("class", "")
                widget.attrs["class"] = (existing_class + " form-select").strip()
            else:
                existing_class = widget.attrs.get("class", "")
                widget.attrs["class"] = (existing_class + " form-control").strip()


class MedicineForm(BootstrapFormMixin, forms.ModelForm):

    class Meta:

        model = Medicine

        fields = "__all__"

        widgets = {

            "description": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Describe the medicine..."}
            ),

            "uses": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Key therapeutic uses..."}
            ),

            "side_effects": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Common side effects..."}
            ),

        }


class PharmacyForm(BootstrapFormMixin, forms.ModelForm):

    class Meta:

        model = Pharmacy

        fields = "__all__"

        widgets = {

            "address": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Full street address..."}
            ),

            "opening_time": forms.TimeInput(
                attrs={"type": "time"}
            ),

            "closing_time": forms.TimeInput(
                attrs={"type": "time"}
            ),

        }


class InventoryForm(BootstrapFormMixin, forms.ModelForm):

    class Meta:

        model = Inventory

        fields = "__all__"

        widgets = {

            "expiry_date": forms.DateInput(
                attrs={"type": "date"}
            ),

            "expected_restock": forms.DateInput(
                attrs={"type": "date"}
            ),

        }


class RegisterForm(BootstrapFormMixin, forms.ModelForm):

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Choose a strong password"})
    )

    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={"placeholder": "Repeat your password"})
    )

    role = forms.ChoiceField(
        choices=UserProfile.ROLE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"})
    )

    # Optional fields for Pharmacy account registration
    pharmacy_option = forms.ChoiceField(
        choices=[
            ("existing", "Link to an Existing Pharmacy"),
            ("new", "Register a New Pharmacy"),
        ],
        required=False,
        initial="existing",
        widget=forms.RadioSelect(attrs={"class": "form-check-input"})
    )

    existing_pharmacy = forms.ModelChoiceField(
        queryset=Pharmacy.objects.all(),
        required=False,
        empty_label="-- Select Existing Pharmacy --",
        widget=forms.Select(attrs={"class": "form-select"})
    )

    new_pharmacy_name = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={"placeholder": "e.g. HealthCare Pharmacy"})
    )

    new_pharmacy_phone = forms.CharField(
        required=False,
        max_length=15,
        widget=forms.TextInput(attrs={"placeholder": "e.g. +91 9876543210"})
    )

    new_pharmacy_city = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": "e.g. Chennai"})
    )

    new_pharmacy_address = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Pharmacy address..."})
    )

    class Meta:

        model = User

        fields = [
            "first_name",
            "email",
            "username",
            "password",
        ]

        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "Enter your full name"}),
            "email": forms.EmailInput(attrs={"placeholder": "name@example.com"}),
            "username": forms.TextInput(attrs={"placeholder": "Choose a unique username"}),
        }

    def clean(self):

        cleaned_data = super().clean()

        if cleaned_data.get("password") != cleaned_data.get("confirm_password"):

            raise forms.ValidationError(
                "Passwords do not match."
            )

        role = cleaned_data.get("role")
        if role == "Pharmacy":
            option = cleaned_data.get("pharmacy_option")
            if option == "existing" and not cleaned_data.get("existing_pharmacy"):
                # If existing selected but none picked, check if any pharmacies exist
                if Pharmacy.objects.exists():
                    raise forms.ValidationError("Please select a pharmacy to link to your account.")
            elif option == "new":
                if not cleaned_data.get("new_pharmacy_name"):
                    raise forms.ValidationError("Please provide a name for your new pharmacy.")

        return cleaned_data