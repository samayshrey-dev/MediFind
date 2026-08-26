import math
import logging
import urllib.request
import urllib.parse
import json
from decimal import Decimal
from django.core.cache import cache
from django.utils import timezone
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


class OSMPharmacyService:
    """
    OpenStreetMap Overpass Pharmacy Location Discovery Service.
    Retrieves real mapped pharmacy locations via OpenStreetMap Overpass API.
    Rule: Contains ONLY spatial location & contact metadata.
    Does NOT invent or fabricate pharmacy inventory, prices, or stock.
    """
    OVERPASS_ENDPOINTS = [
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    ]

    @classmethod
    def get_nearby_pharmacies(cls, user_lat, user_lng, radius_km=5.0, query=None):
        """
        Retrieves nearby mapped pharmacies within radius_km using Overpass API
        with server-side DB caching fallback and Haversine distance sorting.
        """
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

        # Check Cache Key (rounded to 2 decimals ~1km grid)
        cache_key = f"osm_pharmacies_{round(user_lat, 2)}_{round(user_lng, 2)}_{round(radius_km, 1)}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return cls._process_and_sort_candidates(cached_data, user_lat, user_lng, radius_km, query)

        # Build Geographic Bounding Box
        delta_lat = radius_km / 111.0
        delta_lng = radius_km / (111.0 * max(0.1, math.cos(math.radians(user_lat))))

        south = round(user_lat - delta_lat, 5)
        north = round(user_lat + delta_lat, 5)
        west = round(user_lng - delta_lng, 5)
        east = round(user_lng + delta_lng, 5)

        overpass_ql = f"""[out:json][timeout:10];
(
  node["amenity"="pharmacy"]({south},{west},{north},{east});
  way["amenity"="pharmacy"]({south},{west},{north},{east});
);
out center;"""

        fetched_nodes = []
        for endpoint in cls.OVERPASS_ENDPOINTS:
            try:
                req = urllib.request.Request(
                    endpoint,
                    data=urllib.parse.urlencode({"data": overpass_ql}).encode("utf-8"),
                    headers={"User-Agent": "MediFind-Pharmacy-Discovery/1.0 (Healthcare Platform)"}
                )
                with urllib.request.urlopen(req, timeout=8) as response:
                    if response.status == 200:
                        payload = json.loads(response.read().decode("utf-8"))
                        fetched_nodes = payload.get("elements", [])
                        break
            except Exception as e:
                logger.warning(f"Overpass API endpoint {endpoint} failed: {e}")

        parsed_locations = []

        if fetched_nodes:
            for elem in fetched_nodes:
                tags = elem.get("tags", {})
                elem_id = f"{elem.get('type', 'node')}/{elem.get('id')}"
                
                # Get Lat/Lng for nodes or ways (center)
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

                address_parts = [p for p in [housenumber, street, suburb] if p]
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

                # Upsert into SQLite OSMPharmacyLocation DB Cache
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

            # Store in Django cache for 1 hour
            cache.set(cache_key, parsed_locations, 3600)

        # Local OSM DB Storage: Include local OSMPharmacyLocation database records within bounding box
        all_db_nodes = OSMPharmacyLocation.objects.all()[:200]
        for d in all_db_nodes:
            plat = float(d.latitude)
            plng = float(d.longitude)
            dist = haversine_distance(user_lat, user_lng, plat, plng)
            if dist <= radius_km * 1.5:
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

        # Final Fallback: Also include active verified internal platform pharmacies
        internal_pharmacies = Pharmacy.objects.filter(is_active=True)
        for p in internal_pharmacies:
            plat = float(p.latitude)
            plng = float(p.longitude)
            dist = haversine_distance(user_lat, user_lng, plat, plng)
            if dist <= radius_km:
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

            if dist_km > radius_km * 1.2:
                continue

            dedup_key = (item["name"].lower().strip(), round(plat, 4), round(plng, 4))
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
