import os
import sys
import django

sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from PIL import Image, ImageDraw, ImageFilter
from medifind.models import Medicine

MEDIA_MEDICINES_DIR = os.path.join(os.getcwd(), 'media', 'medicines')
os.makedirs(MEDIA_MEDICINES_DIR, exist_ok=True)

PALETTES = {
    'Pain Relief': ('#0f766e', '#0d9488', '#ccfbf1', '#14b8a6'),
    'Antibiotic': ('#0284c7', '#0369a1', '#e0f2fe', '#38bdf8'),
    'Vitamin': ('#d97706', '#b45309', '#fef3c7', '#fbbf24'),
    'Allergy': ('#7c3aed', '#6d28d9', '#f3e8ff', '#a78bfa'),
    'Diabetes': ('#e11d48', '#be123c', '#ffe4e6', '#fb7185'),
    'Heart': ('#dc2626', '#b91c1c', '#fee2e2', '#f87171'),
    'Other': ('#475569', '#334155', '#f1f5f9', '#94a3b8')
}

def create_medicine_image(med):
    cat = med.category if med.category in PALETTES else 'Other'
    c_main, c_dark, c_light, c_accent = PALETTES[cat]
    
    W, H = 600, 600
    img = Image.new('RGB', (W, H), color='#f1f5f9')
    draw = ImageDraw.Draw(img)
    
    # Background soft pattern
    for y in range(0, H, 24):
        for x in range(0, W, 24):
            draw.ellipse([x, y, x+2, y+2], fill='#cbd5e1')
            
    # Shadow
    shadow = Image.new('RGBA', (W, H), (0,0,0,0))
    s_draw = ImageDraw.Draw(shadow)
    s_draw.rounded_rectangle([75, 85, 525, 515], radius=28, fill=(15, 23, 42, 35))
    shadow = shadow.filter(ImageFilter.GaussianBlur(12))
    img.paste(shadow, (0, 0), shadow)
    
    # Main Box Container
    box_rect = [70, 80, 530, 510]
    draw.rounded_rectangle(box_rect, radius=28, fill='#ffffff', outline='#cbd5e1', width=2)
    
    # Header Strip on Box
    draw.rounded_rectangle([70, 80, 530, 190], radius=28, fill=c_main)
    draw.rectangle([70, 160, 530, 190], fill=c_main)
    
    # Category Pill Badge inside box header
    draw.rounded_rectangle([100, 105, 240, 140], radius=15, fill='#ffffff')
    draw.text((115, 115), cat.upper(), fill=c_main)
    
    # Rx Badge
    if med.prescription_required:
        draw.rounded_rectangle([420, 105, 495, 140], radius=15, fill='#ef4444')
        draw.text((440, 115), 'Rx', fill='#ffffff')
    else:
        draw.rounded_rectangle([420, 105, 495, 140], radius=15, fill='#10b981')
        draw.text((435, 115), 'OTC', fill='#ffffff')
        
    # Brand Name Header
    draw.text((100, 155), f'BRAND: {med.brand.upper()}', fill='#f8fafc')
    
    # Medicine Name
    draw.text((100, 220), f"{med.name}", fill='#0f172a')
    
    # Dosage & Form Pill
    draw.rounded_rectangle([100, 290, 320, 330], radius=14, fill=c_light, outline=c_accent, width=2)
    draw.text((115, 303), f'DOSAGE: {med.dosage}', fill=c_dark)
    
    # Pill capsule graphic illustration
    draw.ellipse([360, 270, 480, 390], fill=c_light, outline=c_main, width=3)
    draw.rounded_rectangle([390, 300, 450, 360], radius=20, fill=c_main)
    draw.rectangle([420, 300, 450, 360], fill=c_accent)
    
    # Bottom Manufacturer details
    draw.line([100, 420, 500, 420], fill='#e2e8f0', width=2)
    draw.text((100, 440), 'MediFind Verified Product - 100% Authentic', fill='#64748b')
    draw.text((100, 465), f'Category: {med.category} | Form: Tablet / Capsule', fill='#94a3b8')
    
    safe_name = med.name.lower().replace(" ", "_").replace("/", "_")
    filename = f'med_{med.id}_{safe_name}.png'
    filepath = os.path.join(MEDIA_MEDICINES_DIR, filename)
    img.save(filepath, 'PNG', quality=95)
    
    med.image = f'medicines/{filename}'
    med.save()
    print(f'Medicine #{med.id}: {med.name} -> medicines/{filename}')

if __name__ == '__main__':
    for med in Medicine.objects.all():
        create_medicine_image(med)
    print('ALL MEDICINES UPDATED WITH IMAGES SUCCESSFULLY!')
