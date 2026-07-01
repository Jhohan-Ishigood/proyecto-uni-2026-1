import urllib.request
from PIL import Image
from io import BytesIO

url = "https://images.unsplash.com/photo-1567620832903-9fc6debc209f?w=500&auto=format&fit=crop&q=60"

try:
    print("Intentando descargar imagen...")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as response:
        img_data = response.read()
    img = Image.open(BytesIO(img_data))
    print(f"Descargada correctamente! Formato: {img.format}, Tamaño: {img.size}")
except Exception as e:
    print("Error al descargar:", e)
