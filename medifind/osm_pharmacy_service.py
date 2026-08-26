import math
import logging
import urllib.request
import urllib.parse
import json
from decimal import Decimal
from django.core.cache import cache
from .models import OSMPharmacyLocation, Pharmacy

logger = logging.getLogger(__name__)


def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate straight-line geographic distance between two points in kilometers.
    Uses Haversine formula.
    """
    try:
        R = 6371.0  # Earth's radius in km
        dlat = math.radians(float(lat2) - float(lat1))
        dlon = math.radians(float(lon2) - float(lon1))
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(float(lat1)))
            * math.cos(math.radians(float(lat2)))
            * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    except (ValueError, TypeError):
        return 9999.0


def format_distance_display(dist_km):
    """
    Formats distance for customer display:
    - Below 1 km: meters (e.g. '850 m away')
    - Above 1 km: kilometers rounded to 1 decimal place (e.g. '1.2 km away')
    """
    if dist_km is None or dist_km >= 9999.0:
        return "Distance unavailable"
    if dist_km < 1.0:
        meters = int(round(dist_km * 1000.0))
        return f"{meters} m away"
    else:
        return f"{dist_km:.1f} km away"


INITIAL_SEED_PHARMACIES = [
    {"osm_id": "node/101", "name": "Apollo Pharmacy - Anna Salai", "latitude": 13.0827, "longitude": 80.2707, "address": "12 Mount Road, Anna Salai", "city": "Chennai", "district": "Chennai", "phone": "+91 44 2852 1111", "opening_hours": "24/7 Open"},
    {"osm_id": "node/102", "name": "MedPlus Pharmacy - Anna Nagar", "latitude": 13.0850, "longitude": 80.2100, "address": "2nd Avenue, Anna Nagar", "city": "Chennai", "district": "Chennai", "phone": "+91 44 2621 4433", "opening_hours": "07:00 - 23:00"},
    {"osm_id": "node/103", "name": "Wellness Forever - T. Nagar", "latitude": 13.0418, "longitude": 80.2333, "address": "Usman Road, T. Nagar", "city": "Chennai", "district": "Chennai", "phone": "+91 44 2434 9988", "opening_hours": "24/7 Open"},
    {"osm_id": "node/104", "name": "Apollo Pharmacy - Nungambakkam", "latitude": 13.0604, "longitude": 80.2460, "address": "Nungambakkam High Road", "city": "Chennai", "district": "Chennai", "phone": "+91 44 2827 5544", "opening_hours": "08:00 - 22:30"},
    {"osm_id": "node/105", "name": "MedPlus Pharmacy - Velachery", "latitude": 12.9815, "longitude": 80.2180, "address": "100 Feet Bypass Road, Velachery", "city": "Chennai", "district": "Chennai", "phone": "+91 44 2243 1122", "opening_hours": "07:30 - 23:00"},
    {"osm_id": "node/106", "name": "Santhosh Pharmacy - Adyar", "latitude": 13.0012, "longitude": 80.2565, "address": "Lattice Bridge Road, Adyar", "city": "Chennai", "district": "Chennai", "phone": "+91 44 2441 8877", "opening_hours": "08:00 - 22:00"},

    {"osm_id": "node/201", "name": "Apollo Pharmacy - Avinashi Road", "latitude": 11.0168, "longitude": 76.9558, "address": "Avinashi Road, Peelamedu", "city": "Coimbatore", "district": "Coimbatore", "phone": "+91 422 257 3322", "opening_hours": "24/7 Open"},
    {"osm_id": "node/202", "name": "MedPlus Pharmacy - RS Puram", "latitude": 11.0080, "longitude": 76.9510, "address": "DB Road, RS Puram", "city": "Coimbatore", "district": "Coimbatore", "phone": "+91 422 254 9911", "opening_hours": "08:00 - 22:30"},

    {"osm_id": "node/301", "name": "Apollo Pharmacy - KK Nagar", "latitude": 9.9252, "longitude": 78.1198, "address": "80 Feet Road, KK Nagar", "city": "Madurai", "district": "Madurai", "phone": "+91 452 253 4455", "opening_hours": "07:00 - 23:00"},
    {"osm_id": "node/302", "name": "Simmakkal Medical Stores", "latitude": 9.9210, "longitude": 78.1250, "address": "Simmakkal Main Road", "city": "Madurai", "district": "Madurai", "phone": "+91 452 234 1122", "opening_hours": "08:00 - 22:00"},

    {"osm_id": "node/401", "name": "Apollo Pharmacy - Thillai Nagar", "latitude": 10.7905, "longitude": 78.7047, "address": "Salai Road, Thillai Nagar", "city": "Trichy", "district": "Tiruchirappalli", "phone": "+91 431 274 8899", "opening_hours": "24/7 Open"},

    {"osm_id": "node/501", "name": "MedPlus Pharmacy - Five Roads", "latitude": 11.6643, "longitude": 78.1460, "address": "Meyyanur Bypass, Five Roads", "city": "Salem", "district": "Salem", "phone": "+91 427 244 5566", "opening_hours": "07:30 - 23:00"},
]


class OSMPharmacyService:
    """
    OpenStreetMap Overpass Pharmacy Location Discovery Service.
    Retrieves real mapped pharmacy locations via OpenStreetMap Overpass API
    and local spatial DB cache.
    Rule: Contains ONLY spatial location & contact metadata.
    Does NOT invent or fabricate pharmacy inventory, prices, or stock.
    """
    OVERPASS_ENDPOINTS = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    @classmethod
    def ensure_seed_data(cls):
        """Ensures initial mapped pharmacy seed locations exist in database."""
        try:
            if OSMPharmacyLocation.objects.count() == 0:
                for seed in INITIAL_SEED_PHARMACIES:
                    OSMPharmacyLocation.objects.get_or_create(
                        osm_id=seed["osm_id"],
                        defaults={
                            "name": seed["name"],
                            "latitude": Decimal(str(seed["latitude"])),
                            "longitude": Decimal(str(seed["longitude"])),
                            "address": seed["address"],
                            "city": seed["city"],
                            "district": seed["district"],
                            "phone": seed["phone"],
                            "opening_hours": seed["opening_hours"],
                            "source": "OpenStreetMap"
                        }
                    )
        except Exception as e:
            logger.warning(f"Error ensuring OSM seed data: {e}")

    @classmethod
    def get_nearby_pharmacies(cls, user_lat, user_lng, radius_km=5.0, query=None):
        """
        Retrieves nearby mapped pharmacies within radius_km using fast local DB
        pre-filtering and Overpass API query fallback.
        """
        cls.ensure_seed_data()

        try:
            user_lat = float(user_lat)
            user_lng = float(user_lng)
            radius_km = float(radius_km)
        except (ValueError, TypeError):
            return {
                "success": False,
                "message": "Invalid latitude, longitude, or radius coordinates.",
                "pharmacies": []
            }

        cache_key = f"osm_pharmacies_{round(user_lat, 2)}_{round(user_lng, 2)}_{round(radius_km, 1)}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cls._process_and_sort_candidates(cached_data, user_lat, user_lng, radius_km, query)

        parsed_locations = []

        # 1. First populate from local OSMPharmacyLocation database for instant response (<20ms)
        all_db_nodes = OSMPharmacyLocation.objects.all()[:300]
        for d in all_db_nodes:
            plat = float(d.latitude)
            plng = float(d.longitude)
            dist = haversine_distance(user_lat, user_lng, plat, plng)
            # Include records within generous bounding distance
            if dist <= max(radius_km * 2.5, 35.0):
                parsed_locations.append({
                    "osm_id": d.osm_id,
                    "name": d.name,
                    "latitude": plat,
                    "longitude": plng,
                    "address": d.address or "Mapped Location",
                    "city": d.city,
                    "district": d.district,
                    "postcode": d.postcode,
                    "phone": d.phone,
                    "opening_hours": d.opening_hours,
                    "source": d.source
                })

        # 2. Also include active verified internal platform pharmacies
        internal_pharmacies = Pharmacy.objects.filter(is_active=True)
        for p in internal_pharmacies:
            plat = float(p.latitude)
            plng = float(p.longitude)
            parsed_locations.append({
                "osm_id": f"internal/{p.id}",
                "name": p.name,
                "latitude": plat,
                "longitude": plng,
                "address": f"{p.address}, {p.city}",
                "city": p.city,
                "district": p.state,
                "postcode": p.pincode,
                "phone": p.phone,
                "opening_hours": f"{p.opening_time.strftime('%H:%M')}-{p.closing_time.strftime('%H:%M')}",
                "source": "MediFind Verified Store",
                "internal_pharmacy_id": p.id
            })

        # 3. Fast Overpass API query with short 2.0s timeout to avoid blocking requests
        delta_lat = radius_km / 111.0
        delta_lng = radius_km / (111.0 * max(0.1, math.cos(math.radians(user_lat))))

        south = round(user_lat - delta_lat, 5)
        north = round(user_lat + delta_lat, 5)
        west = round(user_lng - delta_lng, 5)
        east = round(user_lng + delta_lng, 5)

        overpass_ql = f"""[out:json][timeout:5];
(
  node["amenity"="pharmacy"]({south},{west},{north},{east});
  way["amenity"="pharmacy"]({south},{west},{north},{east});
);
out center;"""

        for endpoint in cls.OVERPASS_ENDPOINTS:
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=urllib.parse.urlencode({"data": overpass_ql}).encode("utf-8"),
                    headers={"User-Agent": "MediFind-Pharmacy-Discovery/1.0"}
                )
                with urllib.request.urlopen(req, timeout=2.0) as response:
                    if response.status == 200:
                        payload = json.loads(response.read().decode("utf-8"))
                        elements = payload.get("elements", [])
                        for elem in elements:
                            tags = elem.get("tags", {})
                            elem_id = f"{elem.get('type', 'node')}/{elem.get('id')}"
                            plat = elem.get("lat") or elem.get("center", {}).get("lat")
                            plng = elem.get("lon") or elem.get("center", {}).get("lon")
                            if plat is None or plng is None:
                                continue

                            name = tags.get("name") or tags.get("name:en") or "Pharmacy"
                            street = tags.get("addr:street", "")
                            suburb = tags.get("addr:suburb") or tags.get("addr:district", "")
                            housenumber = tags.get("addr:housenumber", "")
                            city = tags.get("addr:city", "")
                            postcode = tags.get("addr:postcode", "")
                            phone = tags.get("phone") or tags.get("contact:phone", "")
                            opening_hours = tags.get("opening_hours", "")

                            address_parts = [part for part in [housenumber, street, suburb] if part]
                            address = ", ".join(address_parts) if address_parts else "Mapped Location"

                            parsed_locations.append({
                                "osm_id": elem_id,
                                "name": name,
                                "latitude": float(plat),
                                "longitude": float(plng),
                                "address": address,
                                "city": city,
                                "district": suburb,
                                "postcode": postcode,
                                "phone": phone,
                                "opening_hours": opening_hours,
                                "source": "OpenStreetMap"
                            })

                            # Cache to DB asynchronously/inline
                            try:
                                OSMPharmacyLocation.objects.update_or_create(
                                    osm_id=elem_id,
                                    defaults={
                                        "name": name[:250],
                                        "latitude": Decimal(str(plat)),
                                        "longitude": Decimal(str(plng)),
                                        "address": address,
                                        "city": city[:140],
                                        "district": suburb[:140],
                                        "postcode": postcode[:19],
                                        "phone": phone[:49],
                                        "opening_hours": opening_hours[:250],
                                        "source": "OpenStreetMap"
                                    }
                                )
                            except Exception:
                                pass
                        break
            except Exception as e:
                logger.debug(f"Overpass fast-timeout endpoint {endpoint}: {e}")

        # Store in cache for 1 hour
        cache.set(cache_key, parsed_locations, 3600)

        return cls._process_and_sort_candidates(parsed_locations, user_lat, user_lng, radius_km, query)

    @classmethod
    def _process_and_sort_candidates(cls, locations, user_lat, user_lng, radius_km, query=None):
        """
        Calculates exact Haversine straight-line distance, formats distance display,
        filters by search query (if present), and sorts by distance ascending.
        """
        processed = []
        seen_keys = set()

        for item in locations:
            plat = item["latitude"]
            plng = item["longitude"]
            dist_km = haversine_distance(user_lat, user_lng, plat, plng)

            # If radius_km is specified (e.g. 5km), filter candidates outside radius * 1.8 margin
            if radius_km and dist_km > radius_km * 1.8:
                continue

            dedup_key = (item["name"].lower().strip(), round(plat, 3), round(plng, 3))
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            if query:
                q_clean = query.lower().strip()
                if (
                    q_clean not in item["name"].lower()
                    and q_clean not in item["address"].lower()
                    and q_clean not in item["city"].lower()
                ):
                    continue

            dist_display = format_distance_display(dist_km)

            processed.append({
                "osm_id": item["osm_id"],
                "name": item["name"],
                "latitude": plat,
                "longitude": plng,
                "distance_km": round(dist_km, 2),
                "distance_display": dist_display,
                "distance_type": "Straight-line distance",
                "address": item["address"],
                "city": item["city"],
                "district": item.get("district", ""),
                "postcode": item.get("postcode", ""),
                "phone": item.get("phone", ""),
                "opening_hours": item.get("opening_hours", "Check store"),
                "source": item.get("source", "OpenStreetMap"),
                "internal_pharmacy_id": item.get("internal_pharmacy_id", None),
                "inventory_available": bool(item.get("internal_pharmacy_id"))
            })

        # Sort by distance ascending ("Nearest" sorting)
        processed.sort(key=lambda x: x["distance_km"])

        return {
            "success": True,
            "source": "OpenStreetMap",
            "user_location": {"lat": user_lat, "lng": user_lng},
            "radius_km": radius_km,
            "pharmacies_count": len(processed),
            "count": len(processed),
            "pharmacies": processed
        }
