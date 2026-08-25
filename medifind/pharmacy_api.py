import logging
import requests
from datetime import datetime, date
from decimal import Decimal
from django.utils import timezone
from django.db import transaction

from .models import Pharmacy, Medicine, Inventory

logger = logging.getLogger(__name__)


class PharmacyAPIClient:
    """
    Client for querying external Pharmacy POS/ERP systems in real-time
    when a user searches for medicines on MediAI.
    """

    DEFAULT_TIMEOUT_SECONDS = 2.0

    @classmethod
    def query_pharmacy_inventory(cls, pharmacy, query_text):
        """
        Queries a single pharmacy's POS/ERP API for a medicine search query.
        Returns a list of standardized inventory items synced from the API.
        """
        if not pharmacy.api_sync_enabled or not pharmacy.api_endpoint_url:
            return []

        endpoint = pharmacy.api_endpoint_url.strip()

        # SSRF Protection: Ensure endpoint is a safe external HTTP/HTTPS address
        from .security import is_safe_external_url
        if not is_safe_external_url(endpoint):
            logger.warning(f"Blocked unsafe/internal pharmacy API endpoint for {pharmacy.name}: {endpoint}")
            pharmacy.api_sync_status = "Invalid / Disallowed Endpoint"
            pharmacy.save(update_fields=["api_sync_status"])
            return []

        headers = {
            "Accept": "application/json",
            "User-Agent": "MediAI-Pharmacy-Sync/2.0",
        }

        if pharmacy.api_auth_token:
            token = pharmacy.api_auth_token.strip()
            headers["Authorization"] = f"Bearer {token}"
            headers["X-API-Key"] = token

        params = {
            "q": query_text,
            "medicine": query_text,
            "pharmacy_id": pharmacy.id,
        }

        try:
            response = requests.get(
                endpoint,
                headers=headers,
                params=params,
                timeout=cls.DEFAULT_TIMEOUT_SECONDS
            )

            if response.status_code == 200:
                data = response.json()
                pharmacy.api_sync_status = "Connected & Active"
                pharmacy.api_last_synced_at = timezone.now()
                pharmacy.save(update_fields=["api_sync_status", "api_last_synced_at"])

                items = cls._parse_and_sync_items(pharmacy, data)
                return items
            else:
                pharmacy.api_sync_status = f"HTTP Error {response.status_code}"
                pharmacy.save(update_fields=["api_sync_status"])
                logger.warning(f"Pharmacy API returned non-200 for {pharmacy.name}: {response.status_code}")
                return []

        except requests.exceptions.Timeout:
            pharmacy.api_sync_status = "Timeout (Fallback to Cached)"
            pharmacy.save(update_fields=["api_sync_status"])
            logger.warning(f"Pharmacy API timeout for {pharmacy.name} ({endpoint})")
            return []

        except Exception as e:
            pharmacy.api_sync_status = f"Error: {str(e)[:50]}"
            pharmacy.save(update_fields=["api_sync_status"])
            logger.error(f"Error querying Pharmacy API for {pharmacy.name}: {str(e)}")
            return []

    @classmethod
    def query_all_enabled_pharmacies(cls, query_text, pharmacies_qs=None):
        """
        Queries all pharmacies with API integration enabled for a given search query.
        Returns a dict of {pharmacy_id: [synced_inventory_items]}.
        """
        if not query_text or len(query_text.strip()) < 2:
            return {}

        if pharmacies_qs is None:
            pharmacies_qs = Pharmacy.objects.filter(is_active=True, api_sync_enabled=True)
        else:
            pharmacies_qs = pharmacies_qs.filter(is_active=True, api_sync_enabled=True)

        results = {}
        for pharmacy in pharmacies_qs:
            synced_items = cls.query_pharmacy_inventory(pharmacy, query_text)
            if synced_items:
                results[pharmacy.id] = synced_items

        return results

    @classmethod
    def test_connection(cls, pharmacy, test_query="Dolo 650"):
        """
        Tests connection to the pharmacy's configured POS/ERP API endpoint.
        Returns a dict with connectivity details.
        """
        if not pharmacy.api_endpoint_url:
            return {
                "success": False,
                "message": "No API endpoint URL configured.",
                "status_code": None,
                "latency_ms": None,
                "sample_data": None
            }

        endpoint = pharmacy.api_endpoint_url.strip()
        headers = {
            "Accept": "application/json",
            "User-Agent": "MediAI-Pharmacy-Sync/2.0",
        }
        if pharmacy.api_auth_token:
            token = pharmacy.api_auth_token.strip()
            headers["Authorization"] = f"Bearer {token}"
            headers["X-API-Key"] = token

        params = {
            "q": test_query,
            "medicine": test_query,
            "pharmacy_id": pharmacy.id,
            "test": "true"
        }

        start_time = timezone.now()
        try:
            response = requests.get(
                endpoint,
                headers=headers,
                params=params,
                timeout=4.0
            )
            latency_ms = int((timezone.now() - start_time).total_seconds() * 1000)

            if response.status_code == 200:
                data = response.json()
                pharmacy.api_sync_status = "Connected & Verified"
                pharmacy.api_last_synced_at = timezone.now()
                pharmacy.save(update_fields=["api_sync_status", "api_last_synced_at"])
                return {
                    "success": True,
                    "message": f"Successfully connected to Pharmacy API ({latency_ms}ms latency).",
                    "status_code": 200,
                    "latency_ms": latency_ms,
                    "sample_data": data
                }
            else:
                pharmacy.api_sync_status = f"HTTP Error {response.status_code}"
                pharmacy.save(update_fields=["api_sync_status"])
                return {
                    "success": False,
                    "message": f"Pharmacy API responded with HTTP status {response.status_code}.",
                    "status_code": response.status_code,
                    "latency_ms": latency_ms,
                    "sample_data": None
                }
        except requests.exceptions.Timeout:
            pharmacy.api_sync_status = "Connection Timeout (> 4.0s)"
            pharmacy.save(update_fields=["api_sync_status"])
            return {
                "success": False,
                "message": "Connection timed out after 4.0 seconds. Ensure the endpoint is reachable.",
                "status_code": 408,
                "latency_ms": None,
                "sample_data": None
            }
        except Exception as e:
            pharmacy.api_sync_status = f"Connection Failed: {str(e)[:40]}"
            pharmacy.save(update_fields=["api_sync_status"])
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "status_code": 500,
                "latency_ms": None,
                "sample_data": None
            }

    @classmethod
    def _parse_and_sync_items(cls, pharmacy, data):
        """
        Parses raw API JSON response and synchronizes local Inventory and Medicine models.
        """
        raw_items = []
        if isinstance(data, list):
            raw_items = data
        elif isinstance(data, dict):
            if "items" in data and isinstance(data["items"], list):
                raw_items = data["items"]
            elif "medicines" in data and isinstance(data["medicines"], list):
                raw_items = data["medicines"]
            elif "inventory" in data and isinstance(data["inventory"], list):
                raw_items = data["inventory"]
            elif "data" in data and isinstance(data["data"], list):
                raw_items = data["data"]
            elif "medicine" in data or "name" in data:
                raw_items = [data]

        synced_objects = []
        with transaction.atomic():
            for entry in raw_items:
                if not isinstance(entry, dict):
                    continue

                med_name = entry.get("name") or entry.get("medicine") or entry.get("medicine_name") or ""
                med_name = str(med_name).strip()
                if not med_name:
                    continue

                brand = entry.get("brand") or entry.get("manufacturer") or "Generic"
                category = entry.get("category") or "General Health"
                dosage = entry.get("dosage") or entry.get("strength") or "Standard"
                description = entry.get("description") or f"{med_name} {dosage}"
                uses = entry.get("uses") or "Health Treatment"
                side_effects = entry.get("side_effects") or "Consult physician"
                prescription_required = bool(entry.get("prescription_required", False))

                # Upsert Medicine
                medicine, _ = Medicine.objects.get_or_create(
                    name=med_name,
                    defaults={
                        "brand": brand,
                        "category": category,
                        "dosage": dosage,
                        "description": description,
                        "uses": uses,
                        "side_effects": side_effects,
                        "prescription_required": prescription_required,
                    }
                )

                # Parse numeric inventory values
                try:
                    price_val = Decimal(str(entry.get("price") or entry.get("mrp") or "20.00"))
                except Exception:
                    price_val = Decimal("20.00")

                try:
                    quantity_val = int(entry.get("quantity") or entry.get("stock") or 0)
                except Exception:
                    quantity_val = 0

                batch_number = str(entry.get("batch_number") or entry.get("batch") or f"API-{timezone.now().strftime('%m%y')}").strip()
                package_size = str(entry.get("package_size") or entry.get("pack_size") or "Strip of 15").strip()
                sku_code = str(entry.get("sku_code") or entry.get("sku") or "").strip()

                # Parse expiry date
                exp_date = timezone.now().date() + timezone.timedelta(days=365)
                raw_exp = entry.get("expiry_date") or entry.get("expiry")
                if raw_exp:
                    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                        try:
                            exp_date = datetime.strptime(str(raw_exp).strip(), fmt).date()
                            break
                        except ValueError:
                            pass

                # Upsert Inventory
                inv, created = Inventory.objects.update_or_create(
                    pharmacy=pharmacy,
                    medicine=medicine,
                    package_size=package_size,
                    defaults={
                        "price": price_val,
                        "quantity": quantity_val,
                        "batch_number": batch_number,
                        "expiry_date": exp_date,
                        "sku_code": sku_code or f"{med_name[:6].upper()}-{package_size[:4].replace(' ', '').upper()}",
                    }
                )
                inv.is_live_api = True
                synced_objects.append(inv)

        return synced_objects


class MockPharmacyAPIService:
    """
    Simulates a real-world Pharmacy POS/ERP external API for local testing,
    demonstration, and integration verification.
    """

    MOCK_CATALOG = [
        {
            "medicine_name": "Dolo 650",
            "brand": "Micro Labs",
            "category": "Pain Relief",
            "dosage": "650mg",
            "price": 30.50,
            "quantity": 120,
            "batch_number": "DOLO-2026-X4",
            "expiry_date": "2027-06-30",
            "package_size": "Strip of 15",
            "sku_code": "DOLO650-S15",
            "available": True,
        },
        {
            "medicine_name": "Azithromycin 500mg",
            "brand": "Zithrocare",
            "category": "Antibiotic",
            "dosage": "500mg",
            "price": 115.00,
            "quantity": 45,
            "batch_number": "AZI-2026-B1",
            "expiry_date": "2027-03-15",
            "package_size": "Strip of 10",
            "sku_code": "AZI500-S10",
            "available": True,
        },
        {
            "medicine_name": "Paracetamol 500mg",
            "brand": "Calpol",
            "category": "Fever & Cold",
            "dosage": "500mg",
            "price": 18.00,
            "quantity": 200,
            "batch_number": "CAL-9982",
            "expiry_date": "2027-11-30",
            "package_size": "Strip of 15",
            "sku_code": "CAL500-S15",
            "available": True,
        },
        {
            "medicine_name": "Metformin 500mg",
            "brand": "Glycomet",
            "category": "Diabetes Care",
            "dosage": "500mg",
            "price": 42.00,
            "quantity": 85,
            "batch_number": "GLY-2026-M8",
            "expiry_date": "2028-01-20",
            "package_size": "Strip of 10",
            "sku_code": "GLY500-S10",
            "available": True,
        },
        {
            "medicine_name": "Amoxicillin 500mg",
            "brand": "Novamox",
            "category": "Antibiotic",
            "dosage": "500mg",
            "price": 88.50,
            "quantity": 60,
            "batch_number": "NOV-5512",
            "expiry_date": "2027-08-10",
            "package_size": "Strip of 10",
            "sku_code": "NOV500-S10",
            "available": True,
        },
        {
            "medicine_name": "Pantoprazole 40mg",
            "brand": "Pan 40",
            "category": "Digestive Health",
            "dosage": "40mg",
            "price": 95.00,
            "quantity": 90,
            "batch_number": "PAN-7731",
            "expiry_date": "2027-12-31",
            "package_size": "Strip of 15",
            "sku_code": "PAN40-S15",
            "available": True,
        },
        {
            "medicine_name": "Cetirizine 10mg",
            "brand": "Cetzine",
            "category": "Allergy",
            "dosage": "10mg",
            "price": 22.00,
            "quantity": 150,
            "batch_number": "CET-3321",
            "expiry_date": "2027-09-15",
            "package_size": "Strip of 10",
            "sku_code": "CET10-S10",
            "available": True,
        },
        {
            "medicine_name": "Telmisartan 40mg",
            "brand": "Telma 40",
            "category": "Blood Pressure",
            "dosage": "40mg",
            "price": 135.00,
            "quantity": 70,
            "batch_number": "TEL-8812",
            "expiry_date": "2028-04-30",
            "package_size": "Strip of 15",
            "sku_code": "TEL40-S15",
            "available": True,
        }
    ]

    @classmethod
    def search_mock_inventory(cls, query_text=""):
        """
        Filters mock catalog by medicine name, brand, or category.
        """
        q = str(query_text or "").strip().lower()
        if not q:
            return cls.MOCK_CATALOG

        matched = []
        for item in cls.MOCK_CATALOG:
            name = item["medicine_name"].lower()
            brand = item["brand"].lower()
            cat = item["category"].lower()
            if q in name or q in brand or q in cat or any(tok in name or tok in brand for tok in q.split()):
                matched.append(item)

        return matched if matched else cls.MOCK_CATALOG[:3]
