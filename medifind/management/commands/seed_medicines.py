from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, date, time
from decimal import Decimal
from medifind.models import Medicine, Pharmacy, Inventory


class Command(BaseCommand):
    help = "Seeds realistic demo medicine catalog and pharmacy inventory across useful healthcare categories."

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.NOTICE("Seeding MedFinder realistic medicine catalog and demo inventory..."))

        # 1. Seed Real Pharmacies with Verified Coordinates
        pharmacies_data = [
            {
                "name": "Apollo Pharmacy Anna Nagar",
                "owner_name": "Dr. R. Apollo",
                "phone": "+91 98401 23456",
                "email": "annanagar@apollopharmacy.in",
                "address": "2nd Avenue, Anna Nagar",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "pincode": "600040",
                "latitude": Decimal("13.0850000"),
                "longitude": Decimal("80.2100000"),
                "opening_time": time(8, 0),
                "closing_time": time(23, 0),
                "is_active": True,
                "is_open": True,
            },
            {
                "name": "MedPlus Pharmacy T. Nagar",
                "owner_name": "S. Venkat",
                "phone": "+91 98402 34567",
                "email": "tnagar@medplusindia.com",
                "address": "Pondy Bazaar, T. Nagar",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "pincode": "600017",
                "latitude": Decimal("13.0418000"),
                "longitude": Decimal("80.2341000"),
                "opening_time": time(7, 30),
                "closing_time": time(23, 30),
                "is_active": True,
                "is_open": True,
            },
            {
                "name": "Netmeds Store Adyar",
                "owner_name": "K. Raman",
                "phone": "+91 98403 45678",
                "email": "adyar@netmeds.com",
                "address": "Lattice Bridge Road, Adyar",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "pincode": "600020",
                "latitude": Decimal("13.0012000"),
                "longitude": Decimal("80.2565000"),
                "opening_time": time(8, 30),
                "closing_time": time(22, 0),
                "is_active": True,
                "is_open": True,
            },
            {
                "name": "Wellness Forever Alwarpet",
                "owner_name": "M. Suresh",
                "phone": "+91 98404 56789",
                "email": "alwarpet@wellnessforever.in",
                "address": "TTK Road, Alwarpet",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "pincode": "600018",
                "latitude": Decimal("13.0334000"),
                "longitude": Decimal("80.2520000"),
                "opening_time": time(0, 0),
                "closing_time": time(23, 59),
                "is_active": True,
                "is_open": True,
            },
            {
                "name": "Muthu Pharmacy Kilpauk",
                "owner_name": "P. Muthukumar",
                "phone": "+91 98405 67890",
                "email": "contact@muthupharmacy.com",
                "address": "Poonamallee High Road, Kilpauk",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "pincode": "600010",
                "latitude": Decimal("13.0780000"),
                "longitude": Decimal("80.2410000"),
                "opening_time": time(9, 0),
                "closing_time": time(21, 30),
                "is_active": True,
                "is_open": True,
            },
            {
                "name": "Health & Glow Chemist Velachery",
                "owner_name": "A. Rajesh",
                "phone": "+91 98406 78901",
                "email": "velachery@healthandglow.com",
                "address": "100 Feet Bypass Road, Velachery",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "pincode": "600042",
                "latitude": Decimal("12.9815000"),
                "longitude": Decimal("80.2180000"),
                "opening_time": time(9, 0),
                "closing_time": time(22, 0),
                "is_active": True,
                "is_open": True,
            },
            {
                "name": "Guardian Pharmacy Nungambakkam",
                "owner_name": "L. Anand",
                "phone": "+91 98407 89012",
                "email": "nungambakkam@guardianpharmacy.in",
                "address": "Khader Nawaz Khan Road, Nungambakkam",
                "city": "Chennai",
                "state": "Tamil Nadu",
                "pincode": "600034",
                "latitude": Decimal("13.0604000"),
                "longitude": Decimal("80.2460000"),
                "opening_time": time(8, 0),
                "closing_time": time(22, 30),
                "is_active": True,
                "is_open": True,
            },
        ]

        pharmacies = {}
        for p_data in pharmacies_data:
            pharm, _ = Pharmacy.objects.update_or_create(
                name=p_data["name"],
                defaults=p_data
            )
            pharmacies[p_data["name"]] = pharm
        self.stdout.write(self.style.SUCCESS(f"Verified {len(pharmacies)} partner pharmacies."))

        # 2. Seed Rich Medicine Catalog Across 16 Categories
        medicines_catalog = [
            # Pain Relief & Fever & Cold
            {
                "name": "Dolo 650",
                "brand": "Micro Labs",
                "category": "Pain Relief",
                "dosage": "Tablet - 650 mg",
                "description": "Fast-acting Paracetamol formulation for symptomatic relief of fever, mild-to-moderate body pain, and headache.",
                "uses": "Fever, headache, toothache, muscle aches, backache",
                "side_effects": "Rare mild allergic reactions or nausea. Consult doctor if fever persists.",
                "prescription_required": False,
            },
            {
                "name": "Paracetamol 500 mg",
                "brand": "Cipla",
                "category": "Pain Relief",
                "dosage": "Tablet - 500 mg",
                "description": "Standard antipyretic and analgesic tablet containing Paracetamol 500 mg.",
                "uses": "Fever reduction and general pain relief",
                "side_effects": "Safe within recommended daily limits. Avoid excessive alcohol intake.",
                "prescription_required": False,
            },
            {
                "name": "Crocin 650",
                "brand": "GSK",
                "category": "Fever & Cold",
                "dosage": "Tablet - 650 mg",
                "description": "Formulated Paracetamol with Fast Release technology for effective fever control.",
                "uses": "High fever, headaches, muscular soreness",
                "side_effects": "Rare skin rash. Do not exceed 4000 mg in 24 hours.",
                "prescription_required": False,
            },
            {
                "name": "Combiflam",
                "brand": "Sanofi",
                "category": "Pain Relief",
                "dosage": "Tablet - 400mg/325mg",
                "description": "Combination of Ibuprofen (400 mg) and Paracetamol (325 mg) for anti-inflammatory pain management.",
                "uses": "Joint pain, dental pain, sprains, dysmenorrhea",
                "side_effects": "Acidity, stomach irritation. Take strictly after food.",
                "prescription_required": False,
            },
            {
                "name": "Sinarest Tablet",
                "brand": "Centaur",
                "category": "Fever & Cold",
                "dosage": "Tablet",
                "description": "Multi-symptom cold formulation with Paracetamol, Phenylephrine, and Chlorpheniramine.",
                "uses": "Common cold, nasal congestion, sneezing, sinus headache",
                "side_effects": "Mild drowsiness, dry mouth. Avoid driving after ingestion.",
                "prescription_required": False,
            },

            # Allergy
            {
                "name": "Cetirizine 10 mg",
                "brand": "Dr. Reddy's",
                "category": "Allergy",
                "dosage": "Tablet - 10 mg",
                "description": "Second-generation non-sedating antihistamine for rapid allergic symptom relief.",
                "uses": "Allergic rhinitis, seasonal hay fever, hives, itchy watery eyes",
                "side_effects": "Mild dry mouth or drowsiness in sensitive individuals.",
                "prescription_required": False,
            },
            {
                "name": "Allegra 120 mg",
                "brand": "Sanofi",
                "category": "Allergy",
                "dosage": "Tablet - 120 mg",
                "description": "Fexofenadine hydrochloride formulation for daytime non-drowsy allergy relief.",
                "uses": "Perennial allergic rhinitis, skin allergies, dust allergy",
                "side_effects": "Headache, mild dizziness.",
                "prescription_required": False,
            },
            {
                "name": "Montair-LC",
                "brand": "Cipla",
                "category": "Allergy",
                "dosage": "Tablet - 10mg/5mg",
                "description": "Combination of Montelukast and Levocetirizine for persistent allergic symptoms and wheezing.",
                "uses": "Allergic asthma, chronic rhinitis, dust and pollen allergies",
                "side_effects": "Headache, fatigue, sleep disturbances.",
                "prescription_required": True,
            },

            # Digestive Health
            {
                "name": "Digene Gel Mint",
                "brand": "Abbott",
                "category": "Digestive Health",
                "dosage": "Syrup - 200 ml",
                "description": "Antacid liquid providing soothing, fast relief from acidity, heartburn, and gas.",
                "uses": "Hyperacidity, acid reflux, bloating, indigestion",
                "side_effects": "Rare mild laxative or constipating effect.",
                "prescription_required": False,
            },
            {
                "name": "Pantocid 40 mg",
                "brand": "Sun Pharma",
                "category": "Digestive Health",
                "dosage": "Tablet - 40 mg",
                "description": "Pantoprazole proton pump inhibitor that reduces stomach acid production.",
                "uses": "Gastroesophageal reflux disease (GERD), stomach ulcers, severe acidity",
                "side_effects": "Headache, diarrhea, abdominal discomfort.",
                "prescription_required": True,
            },
            {
                "name": "Electral ORS Powder",
                "brand": "FDC",
                "category": "Digestive Health",
                "dosage": "Sachet - 21.8 g",
                "description": "WHO-recommended Oral Rehydration Salts formula for rapid electrolyte and fluid restoration.",
                "uses": "Dehydration, diarrhea, heat exhaustion, active sports recovery",
                "side_effects": "None when diluted in 1 liter of clean drinking water.",
                "prescription_required": False,
            },
            {
                "name": "Eno Fruit Salt Regular",
                "brand": "GSK",
                "category": "Digestive Health",
                "dosage": "Sachet - 5 g",
                "description": "Fast-acting effervescent antacid powder acting in 6 seconds.",
                "uses": "Instant heartburn and indigestion relief",
                "side_effects": "Transient belching.",
                "prescription_required": False,
            },

            # Vitamins & Supplements
            {
                "name": "Becosules Z",
                "brand": "Pfizer",
                "category": "Vitamins & Supplements",
                "dosage": "Capsule",
                "description": "Comprehensive Vitamin B-Complex with Vitamin C and Zinc for tissue repair and immunity.",
                "uses": "Mouth ulcers, vitamin deficiency, fatigue, immunity booster",
                "side_effects": "Bright yellow urine (normal riboflavin excretion).",
                "prescription_required": False,
            },
            {
                "name": "Neurobion Forte",
                "brand": "Procter & Gamble",
                "category": "Vitamins & Supplements",
                "dosage": "Tablet",
                "description": "Therapeutic B-vitamins formulation (B1, B6, B12) for nerve health and cellular energy.",
                "uses": "Nerve health, tingling sensations, numbness, general weakness",
                "side_effects": "Mild gastrointestinal upset in rare cases.",
                "prescription_required": False,
            },
            {
                "name": "Shelcal 500",
                "brand": "Torrent",
                "category": "Vitamins & Supplements",
                "dosage": "Tablet - 500 mg",
                "description": "Calcium Carbonate with Vitamin D3 for bone strength and density support.",
                "uses": "Bone health, calcium deficiency, osteoporosis prevention",
                "side_effects": "Constipation if adequate water is not consumed.",
                "prescription_required": False,
            },
            {
                "name": "Limcee Vitamin C 500 mg",
                "brand": "Abbott",
                "category": "Vitamins & Supplements",
                "dosage": "Chewable Tablet - 500 mg",
                "description": "Ascorbic Acid chewable antioxidant tablet for skin health and natural immune defense.",
                "uses": "Immune support, scurvy prevention, wound healing",
                "side_effects": "None under recommended daily limits.",
                "prescription_required": False,
            },

            # Diabetes Care
            {
                "name": "Glycomet 500 mg",
                "brand": "USV",
                "category": "Diabetes Care",
                "dosage": "Tablet - 500 mg",
                "description": "Metformin Hydrochloride for glycemic control in Type 2 diabetes management.",
                "uses": "Blood sugar regulation, Type 2 diabetes",
                "side_effects": "Nausea, stomach upset. Take with meals.",
                "prescription_required": True,
            },
            {
                "name": "Januvia 100 mg",
                "brand": "MSD",
                "category": "Diabetes Care",
                "dosage": "Tablet - 100 mg",
                "description": "Sitagliptin DPP-4 inhibitor helping regulate insulin production after meals.",
                "uses": "Type 2 diabetes glycemic maintenance",
                "side_effects": "Upper respiratory symptoms, headache.",
                "prescription_required": True,
            },

            # Blood Pressure & Heart
            {
                "name": "Telma 40 mg",
                "brand": "Glenmark",
                "category": "Blood Pressure",
                "dosage": "Tablet - 40 mg",
                "description": "Telmisartan Angiotensin II receptor blocker for blood pressure control.",
                "uses": "Hypertension, cardiovascular risk reduction",
                "side_effects": "Dizziness, low blood pressure symptoms.",
                "prescription_required": True,
            },
            {
                "name": "Amlodac 5 mg",
                "brand": "Zydus",
                "category": "Blood Pressure",
                "dosage": "Tablet - 5 mg",
                "description": "Amlodipine calcium channel blocker that relaxes vascular smooth muscles.",
                "uses": "High blood pressure, stable angina",
                "side_effects": "Ankle swelling, dizziness, flushing.",
                "prescription_required": True,
            },
            {
                "name": "Ecosprin 75 mg",
                "brand": "USV",
                "category": "Heart",
                "dosage": "Tablet - 75 mg",
                "description": "Low-dose enteric-coated Aspirin for anti-platelet cardiovascular protection.",
                "uses": "Prevention of blood clots, heart attacks, and ischemic stroke",
                "side_effects": "Increased bleeding tendency, heartburn.",
                "prescription_required": True,
            },

            # First Aid & Skin Care
            {
                "name": "Betadine 5% Ointment",
                "brand": "Win-Medicare",
                "category": "First Aid",
                "dosage": "Ointment - 20 g",
                "description": "Povidone-Iodine antiseptic microbicidal ointment for wound healing and infection prevention.",
                "uses": "Cuts, abrasions, burns, minor skin wounds",
                "side_effects": "Local skin irritation in iodine-sensitive individuals.",
                "prescription_required": False,
            },
            {
                "name": "Dettol Antiseptic Liquid",
                "brand": "Reckitt",
                "category": "First Aid",
                "dosage": "Liquid - 250 ml",
                "description": "Chloroxylenol formulation for first aid cleansing, cuts, and surface disinfection.",
                "uses": "Wound disinfection, hygiene cleansing",
                "side_effects": "Do not swallow. Must be diluted before topical use.",
                "prescription_required": False,
            },
            {
                "name": "Candid Dusting Powder",
                "brand": "Glenmark",
                "category": "Skin Care",
                "dosage": "Powder - 100 g",
                "description": "Clotrimazole 1% anti-fungal dusting powder for sweat rashes and fungal skin irritations.",
                "uses": "Prickly heat, athlete's foot, fungal skin infections",
                "side_effects": "Mild burning sensation.",
                "prescription_required": False,
            },

            # Respiratory
            {
                "name": "Ascoril LS Syrup",
                "brand": "Glenmark",
                "category": "Respiratory",
                "dosage": "Syrup - 100 ml",
                "description": "Expectorant combining Levosalbutamol, Ambroxol, and Guaiphenesin for productive chest cough.",
                "uses": "Chest congestion, productive wet cough, bronchitis",
                "side_effects": "Tremors, increased heart rate, dizziness.",
                "prescription_required": True,
            },
            {
                "name": "Benadryl Cough Syrup",
                "brand": "Johnson & Johnson",
                "category": "Respiratory",
                "dosage": "Syrup - 100 ml",
                "description": "Diphenhydramine formulation for soothing dry throat tickles and allergic coughs.",
                "uses": "Dry allergic cough, throat irritation",
                "side_effects": "Drowsiness, mild sedation.",
                "prescription_required": False,
            },

            # Eye Care & Oral Care
            {
                "name": "Refresh Tears Eye Drops",
                "brand": "Allergan",
                "category": "Eye Care",
                "dosage": "Eye Drops - 10 ml",
                "description": "Carboxymethylcellulose 0.5% lubricant eye drops for dry and irritated eyes.",
                "uses": "Dry eye syndrome, screen fatigue, eye burning",
                "side_effects": "Temporary blurred vision immediately following application.",
                "prescription_required": False,
            },
            {
                "name": "Hexidine Mouthwash",
                "brand": "ICPA",
                "category": "Oral Care",
                "dosage": "Liquid - 160 ml",
                "description": "Chlorhexidine Gluconate 0.2% anti-plaque and anti-gingivitis oral antiseptic rinse.",
                "uses": "Gum inflammation, oral hygiene, post-dental surgery care",
                "side_effects": "Temporary tooth staining with prolonged use.",
                "prescription_required": False,
            },

            # Antibiotics
            {
                "name": "Augmentin 625 Duo",
                "brand": "GSK",
                "category": "Antibiotic",
                "dosage": "Tablet - 625 mg",
                "description": "Amoxicillin and Potassium Clavulanate broad-spectrum antibacterial formulation.",
                "uses": "Bacterial respiratory, ear, sinus, and soft tissue infections",
                "side_effects": "Diarrhea, nausea, abdominal discomfort. Must complete prescribed course.",
                "prescription_required": True,
            },
            {
                "name": "Azithral 500 mg",
                "brand": "Alembic",
                "category": "Antibiotic",
                "dosage": "Tablet - 500 mg",
                "description": "Azithromycin macrolide antibiotic for targeted respiratory and throat infections.",
                "uses": "Throat infections, tonsillitis, chest infections",
                "side_effects": "Stomach cramps, diarrhea.",
                "prescription_required": True,
            }
        ]

        medicines = {}
        for m_data in medicines_catalog:
            med, _ = Medicine.objects.update_or_create(
                name=m_data["name"],
                defaults=m_data
            )
            medicines[m_data["name"]] = med
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(medicines)} realistic medicines across {len(set(m['category'] for m in medicines_catalog))} categories."))

        # 3. Seed Realistic DEMO Inventory with Multi-Store Variation
        inventory_configs = [
            # Dolo 650 (High stock and price variations across 5 stores)
            ("Dolo 650", "Apollo Pharmacy Anna Nagar", 50, Decimal("25.00")),
            ("Dolo 650", "MedPlus Pharmacy T. Nagar", 35, Decimal("22.50")),
            ("Dolo 650", "Netmeds Store Adyar", 20, Decimal("24.00")),
            ("Dolo 650", "Wellness Forever Alwarpet", 12, Decimal("26.00")),
            ("Dolo 650", "Muthu Pharmacy Kilpauk", 0, Decimal("22.00")), # Out of stock

            # Paracetamol 500 mg
            ("Paracetamol 500 mg", "Apollo Pharmacy Anna Nagar", 40, Decimal("18.00")),
            ("Paracetamol 500 mg", "MedPlus Pharmacy T. Nagar", 25, Decimal("15.50")),
            ("Paracetamol 500 mg", "Netmeds Store Adyar", 15, Decimal("16.00")),
            ("Paracetamol 500 mg", "Guardian Pharmacy Nungambakkam", 30, Decimal("17.00")),

            # Crocin 650
            ("Crocin 650", "Apollo Pharmacy Anna Nagar", 30, Decimal("32.00")),
            ("Crocin 650", "Wellness Forever Alwarpet", 18, Decimal("30.00")),
            ("Crocin 650", "Health & Glow Chemist Velachery", 22, Decimal("31.50")),

            # Combiflam
            ("Combiflam", "Apollo Pharmacy Anna Nagar", 45, Decimal("42.00")),
            ("Combiflam", "MedPlus Pharmacy T. Nagar", 15, Decimal("39.00")),
            ("Combiflam", "Muthu Pharmacy Kilpauk", 8, Decimal("40.00")),

            # Cetirizine 10 mg
            ("Cetirizine 10 mg", "Apollo Pharmacy Anna Nagar", 60, Decimal("28.00")),
            ("Cetirizine 10 mg", "Netmeds Store Adyar", 40, Decimal("25.00")),
            ("Cetirizine 10 mg", "Guardian Pharmacy Nungambakkam", 20, Decimal("27.00")),

            # Allegra 120 mg
            ("Allegra 120 mg", "MedPlus Pharmacy T. Nagar", 25, Decimal("198.00")),
            ("Allegra 120 mg", "Wellness Forever Alwarpet", 14, Decimal("192.00")),

            # Digene Gel
            ("Digene Gel Mint", "Apollo Pharmacy Anna Nagar", 20, Decimal("145.00")),
            ("Digene Gel Mint", "Netmeds Store Adyar", 12, Decimal("138.00")),
            ("Digene Gel Mint", "Health & Glow Chemist Velachery", 15, Decimal("142.00")),

            # Pantocid 40 mg
            ("Pantocid 40 mg", "Apollo Pharmacy Anna Nagar", 50, Decimal("165.00")),
            ("Pantocid 40 mg", "MedPlus Pharmacy T. Nagar", 30, Decimal("158.00")),

            # Electral ORS
            ("Electral ORS Powder", "Apollo Pharmacy Anna Nagar", 100, Decimal("22.00")),
            ("Electral ORS Powder", "Netmeds Store Adyar", 50, Decimal("21.50")),
            ("Electral ORS Powder", "Muthu Pharmacy Kilpauk", 40, Decimal("22.00")),

            # Becosules Z
            ("Becosules Z", "Apollo Pharmacy Anna Nagar", 80, Decimal("54.00")),
            ("Becosules Z", "MedPlus Pharmacy T. Nagar", 60, Decimal("49.50")),
            ("Becosules Z", "Guardian Pharmacy Nungambakkam", 30, Decimal("52.00")),

            # Shelcal 500
            ("Shelcal 500", "Wellness Forever Alwarpet", 40, Decimal("125.00")),
            ("Shelcal 500", "Netmeds Store Adyar", 25, Decimal("118.00")),

            # Telma 40 mg
            ("Telma 40 mg", "Apollo Pharmacy Anna Nagar", 35, Decimal("210.00")),
            ("Telma 40 mg", "MedPlus Pharmacy T. Nagar", 20, Decimal("199.00")),

            # Betadine 5% Ointment
            ("Betadine 5% Ointment", "Apollo Pharmacy Anna Nagar", 25, Decimal("98.00")),
            ("Betadine 5% Ointment", "Health & Glow Chemist Velachery", 18, Decimal("95.00")),

            # Dettol Antiseptic Liquid
            ("Dettol Antiseptic Liquid", "Apollo Pharmacy Anna Nagar", 50, Decimal("130.00")),
            ("Dettol Antiseptic Liquid", "Muthu Pharmacy Kilpauk", 30, Decimal("125.00")),

            # Refresh Tears Eye Drops
            ("Refresh Tears Eye Drops", "Apollo Pharmacy Anna Nagar", 20, Decimal("185.00")),
            ("Refresh Tears Eye Drops", "Guardian Pharmacy Nungambakkam", 15, Decimal("178.00")),

            # Augmentin 625 Duo
            ("Augmentin 625 Duo", "Apollo Pharmacy Anna Nagar", 30, Decimal("225.00")),
            ("Augmentin 625 Duo", "MedPlus Pharmacy T. Nagar", 18, Decimal("215.00")),
        ]

        seeded_inventory_count = 0
        expiry_sample = date.today() + timedelta(days=365)

        for med_name, pharm_name, qty, price in inventory_configs:
            med = medicines.get(med_name)
            pharm = pharmacies.get(pharm_name)
            if med and pharm:
                Inventory.objects.update_or_create(
                    medicine=med,
                    pharmacy=pharm,
                    defaults={
                        "quantity": qty,
                        "price": price,
                        "batch_number": f"BATCH-{med.id*100 + pharm.id}",
                        "expiry_date": expiry_sample,
                        "minimum_stock": 10,
                    }
                )
                seeded_inventory_count += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {seeded_inventory_count} DEMO inventory records."))
        self.stdout.write(self.style.SUCCESS("All medicine catalog and inventory seeding complete!"))
