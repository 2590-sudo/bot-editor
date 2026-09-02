#!/usr/bin/env python3
"""
Bot de Telegram - Editor de Plantillas v7
- Polling MANUAL: no usa infinity_polling ni thread pools
- Posicionamiento EXACTO: detecta posicion real del texto antes de borrar
- Tamano EXACTO: binary search para matching de altura de pixel
- Inpainting quirurgico sin secuelas
- Clonacion de fuente robusta
- Independiente de Base44: funciona con solo TELEGRAM_BOT_TOKEN
"""

import telebot
import os
import tempfile
import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import easyocr
import logging
import time
import traceback

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
bot = telebot.TeleBot(BOT_TOKEN)

# === OCR (lazy) ===
reader = None
def get_ocr():
    global reader
    if reader is None:
        logging.info("Inicializando EasyOCR...")
        reader = easyocr.Reader(['es', 'en'], gpu=False)
        logging.info("EasyOCR listo")
    return reader

# === FUENTES ===
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')
SYS_FONTS = {
    'DejaVuSans': '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
    'DejaVuSans-Bold': '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
    'DejaVuSerif': '/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf',
    'DejaVuSerif-Bold': '/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf',
}

def download_fonts_if_missing():
    """Descarga fuentes si no estan presentes (para deployment independiente)."""
    import urllib.request
    os.makedirs(FONT_DIR, exist_ok=True)
    font_urls = {
        'Roboto-Regular.ttf': 'https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Regular.ttf',
        'Roboto-Bold.ttf': 'https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Bold.ttf',
        'Roboto-Black.ttf': 'https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Black.ttf',
        'OpenSans-Regular.ttf': 'https://github.com/google/fonts/raw/main/ufl/opensans/static/OpenSans-Regular.ttf',
        'OpenSans-Bold.ttf': 'https://github.com/google/fonts/raw/main/ufl/opensans/static/OpenSans-Bold.ttf',
        'Lato-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/lato/Lato-Regular.ttf',
        'Lato-Bold.ttf': 'https://github.com/google/fonts/raw/main/ofl/lato/Lato-Bold.ttf',
        'Montserrat-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Regular.ttf',
        'Montserrat-Bold.ttf': 'https://github.com/google/fonts/raw/main/ofl/montserrat/static/Montserrat-Bold.ttf',
        'Raleway-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/raleway/static/Raleway-Regular.ttf',
        'Nunito-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/nunito/static/Nunito-Regular.ttf',
        'Poppins-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Regular.ttf',
        'Poppins-Bold.ttf': 'https://github.com/google/fonts/raw/main/ofl/poppins/Poppins-Bold.ttf',
        'Inter-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/inter/Inter-Regular.ttf',
        'PlayfairDisplay-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/playfairdisplay/PlayfairDisplay-Regular.ttf',
        'Anton-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf',
        'BebasNeue-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/bebasneue/BebasNeue-Regular.ttf',
        'Oswald-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/oswald/static/Oswald-Regular.ttf',
        'Pacifico-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/pacifico/Pacifico-Regular.ttf',
        'Lobster-Regular.ttf': 'https://github.com/google/fonts/raw/main/ofl/lobster/Lobster-Regular.ttf',
    }
    for name, url in font_urls.items():
        path = os.path.join(FONT_DIR, name)
        if not os.path.exists(path):
            try:
                logging.info(f"Descargando fuente {name}...")
                urllib.request.urlretrieve(url, path)
            except Exception as e:
                logging.warning(f"No se pudo descargar {name}: {e}")

def load_font_registry():
    fonts = {}
    font_meta = {
        'Roboto-Regular': ('sans', 'normal'), 'Roboto-Bold': ('sans', 'bold'),
        'Roboto-Black': ('sans', 'black'), 'OpenSans-Regular': ('sans', 'normal'),
        'OpenSans-Bold': ('sans', 'bold'), 'Lato-Regular': ('sans', 'normal'),
        'Lato-Bold': ('sans', 'bold'), 'Montserrat-Regular': ('sans', 'normal'),
        'Montserrat-Bold': ('sans', 'bold'), 'Raleway-Regular': ('sans', 'normal'),
        'Nunito-Regular': ('sans', 'normal'), 'Poppins-Regular': ('sans', 'normal'),
        'Poppins-Bold': ('sans', 'bold'), 'Inter-Regular': ('sans', 'normal'),
        'DejaVuSans': ('sans', 'normal'), 'DejaVuSans-Bold': ('sans', 'bold'),
        'DejaVuSerif': ('serif', 'normal'), 'DejaVuSerif-Bold': ('serif', 'bold'),
        'PlayfairDisplay-Regular': ('serif', 'normal'),
        'Anton-Regular': ('display', 'black'), 'BebasNeue-Regular': ('display', 'normal'),
        'Oswald-Regular': ('display', 'normal'),
        'Pacifico-Regular': ('script', 'normal'), 'Lobster-Regular': ('script', 'normal'),
    }
    for name, (category, weight) in font_meta.items():
        path = SYS_FONTS.get(name) or os.path.join(FONT_DIR, f'{name}.ttf')
        if path and os.path.exists(path):
            fonts[name] = {'path': path, 'category': category, 'weight': weight}
    if not fonts:
        fonts['DejaVuSans'] = {'path': SYS_FONTS['DejaVuSans'], 'category': 'sans', 'weight': 'normal'}
    return fonts

# Descargar fuentes si hace falta
if not os.path.isdir(FONT_DIR) or len([f for f in os.listdir(FONT_DIR) if f.endswith('.ttf')]) < 5:
    try:
        download_fonts_if_missing()
    except Exception as e:
        logging.warning(f"Descarga de fuentes fallo (usando system fonts): {e}")

FONT_REGISTRY = load_font_registry()
logging.info(f"Fuentes cargadas: {len(FONT_REGISTRY)}")

# === HELPERS DE ENVIO SEGURO ===
def safe_send(chat_id, text, **kwargs):
    for attempt in range(3):
        try:
            return bot.send_message(chat_id, text, **kwargs)
        except Exception as e:
            logging.warning(f"send_message attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    return None

def safe_reply(message, text, **kwargs):
    for attempt in range(3):
        try:
            return bot.reply_to(message, text, **kwargs)
        except Exception as e:
            logging.warning(f"reply_to attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    return None

def safe_send_photo(chat_id, photo_file, **kwargs):
    for attempt in range(3):
        try:
            return bot.send_photo(chat_id, photo_file, **kwargs)
        except Exception as e:
            logging.warning(f"send_photo attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    return None

def safe_send_document(chat_id, doc_file, **kwargs):
    for attempt in range(3):
        try:
            return bot.send_document(chat_id, doc_file, **kwargs)
        except Exception as e:
            logging.warning(f"send_document attempt {attempt+1} failed: {e}")
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    return None

# === SESIONES ===
UPLOAD_DIR = tempfile.mkdtemp(prefix='plantillas_')
sessions = {}

def get_session(user_id):
    if user_id not in sessions:
        sessions[user_id] = {
            'state': 'idle', 'original_path': None, 'working_path': None,
            'detections': [], 'selected': None, 'edited': set(),
            'available_indices': [],
        }
    return sessions[user_id]

def reset_session(user_id):
    sess = get_session(user_id)
    for key in ['original_path', 'working_path']:
        if sess[key] and os.path.exists(sess[key]):
            try: os.unlink(sess[key])
            except: pass
    sessions[user_id] = {
        'state': 'idle', 'original_path': None, 'working_path': None,
        'detections': [], 'selected': None, 'edited': set(),
        'available_indices': [],
    }

# =====================================================
# INPAINTING QUIRURGICO - Sin secuelas ni sombras
# =====================================================
def erase_text_precise(img, det):
    x, y, w, h = det['x'], det['y'], det['w'], det['h']
    H, W = img.shape[:2]

    pad = max(8, int(min(w, h) * 0.3))
    x1 = max(0, x - pad); y1 = max(0, y - pad)
    x2 = min(W, x + w + pad); y2 = min(H, y + h + pad)

    crop = img[y1:y2, x1:x2].copy()
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bg_mean = np.mean(gray[binary == 255]) if np.any(binary == 255) else 128
    text_mean = np.mean(gray[binary == 0]) if np.any(binary == 0) else 128

    if bg_mean > text_mean:
        text_mask_local = (binary == 0).astype(np.uint8) * 255
        bg_color = np.median(crop[binary == 255], axis=0) if np.any(binary == 255) else np.array([255, 255, 255])
    else:
        text_mask_local = (binary == 255).astype(np.uint8) * 255
        bg_color = np.median(crop[binary == 0], axis=0) if np.any(binary == 0) else np.array([0, 0, 0])

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    text_mask_local = cv2.dilate(text_mask_local, kernel, iterations=2)

    mask_global = np.zeros((H, W), dtype=np.uint8)
    mask_global[y1:y2, x1:x2] = text_mask_local

    result = cv2.inpaint(img, mask_global, inpaintRadius=8, flags=cv2.INPAINT_NS)

    # Segunda pasada para residuos
    result_crop = result[y1:y2, x1:x2]
    result_gray = cv2.cvtColor(result_crop, cv2.COLOR_BGR2GRAY)
    bg_gray = cv2.cvtColor(np.uint8([[bg_color]]), cv2.COLOR_BGR2GRAY)[0][0]
    diff = np.abs(result_gray.astype(int) - int(bg_gray))
    residual_mask = (diff > 25).astype(np.uint8) * 255

    if np.count_nonzero(residual_mask) > 0:
        residual_mask_dil = cv2.dilate(residual_mask, kernel, iterations=1)
        mask_global2 = np.zeros((H, W), dtype=np.uint8)
        mask_global2[y1:y2, x1:x2] = residual_mask_dil
        result = cv2.inpaint(result, mask_global2, inpaintRadius=5, flags=cv2.INPAINT_NS)

    # Suavizado feather
    blend_mask = np.zeros((H, W), dtype=np.uint8)
    blend_mask[y1:y2, x1:x2] = 255
    blend_mask = cv2.GaussianBlur(blend_mask, (21, 21), 0)
    blend_mask_3ch = cv2.merge([blend_mask, blend_mask, blend_mask]) / 255.0
    smoothed = cv2.GaussianBlur(result, (5, 5), 0)
    result = (result * (1 - blend_mask_3ch * 0.3) + smoothed * (blend_mask_3ch * 0.3)).astype(np.uint8)

    return result

# =====================================================
# FUNCION 1: DETECTAR POSICION EXACTA DEL TEXTO
# =====================================================
def detect_exact_position(img, det):
    """
    Detecta la posicion EXACTA de los pixeles de texto reales
    dentro del bounding box del OCR. Devuelve coordenadas precisas
    del texto real (no del bbox del OCR que tiene padding).
    """
    x, y, w, h = det['x'], det['y'], det['w'], det['h']
    H, W = img.shape[:2]

    pad = 2
    x1 = max(0, x - pad); y1 = max(0, y - pad)
    x2 = min(W, x + w + pad); y2 = min(H, y + h + pad)

    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return {'top': y, 'left': x, 'bottom': y + h, 'right': x + w,
                'baseline': y + int(h * 0.75), 'center_x': x + w // 2,
                'center_y': y + h // 2, 'width': w, 'height': h}

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bg_mean = np.mean(gray[binary == 255]) if np.any(binary == 255) else 128
    text_mean = np.mean(gray[binary == 0]) if np.any(binary == 0) else 128

    if bg_mean > text_mean:
        text_mask = (binary == 0)
    else:
        text_mask = (binary == 255)

    row_sums = np.sum(text_mask, axis=1)
    col_sums = np.sum(text_mask, axis=0)

    text_rows = np.where(row_sums > 0)[0]
    text_cols = np.where(col_sums > 0)[0]

    if len(text_rows) > 0 and len(text_cols) > 0:
        tight_top = y1 + int(text_rows[0])
        tight_bottom = y1 + int(text_rows[-1])
        tight_left = x1 + int(text_cols[0])
        tight_right = x1 + int(text_cols[-1])
    else:
        tight_top = y; tight_bottom = y + h
        tight_left = x; tight_right = x + w

    # Detectar baseline aproximada
    if len(text_rows) > 2:
        row_density = row_sums.astype(float)
        lower_third_start = len(row_density) * 2 // 3
        lower_section = row_density[lower_third_start:]
        if len(lower_section) > 0:
            baseline_offset = lower_third_start + int(np.argmax(lower_section))
            baseline = y1 + baseline_offset
        else:
            baseline = tight_bottom
    else:
        baseline = tight_bottom

    return {
        'top': tight_top,
        'left': tight_left,
        'bottom': tight_bottom,
        'right': tight_right,
        'baseline': baseline,
        'center_x': (tight_left + tight_right) // 2,
        'center_y': (tight_top + tight_bottom) // 2,
        'width': tight_right - tight_left,
        'height': tight_bottom - tight_top,
    }

# =====================================================
# FUNCION 2: CALCULAR TAMANO EXACTO DE FUENTE
# =====================================================
def measure_rendered_pixel_height(font, text):
    """Renderiza texto y mide la altura REAL en pixeles visibles."""
    # Usar textbbox via draw
    dummy = Image.new('L', (2000, 500), 0)
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if tw <= 0 or th <= 0:
        return 0, 0
    # Renderizar en canvas temporal
    canvas = Image.new('L', (tw + 20, th + 20), 0)
    d2 = ImageDraw.Draw(canvas)
    d2.text((10 - bbox[0], 10 - bbox[1]), text, fill=255, font=font)
    arr = np.array(canvas)
    # Medir altura real de pixeles visibles
    rows = np.where(np.any(arr > 0, axis=1))[0]
    if len(rows) == 0:
        return 0, tw
    pixel_h = rows[-1] - rows[0] + 1
    # Tambien medir ancho real
    cols = np.where(np.any(arr > 0, axis=0))[0]
    pixel_w = cols[-1] - cols[0] + 1 if len(cols) > 0 else tw
    return pixel_h, pixel_w


def calculate_exact_font_size(font_path, target_height, new_text, max_width=None):
    """
    Usa binary search para encontrar el font_size exacto donde
    el texto renderizado tiene la misma altura de PIXELES VISIBLES
    que el texto original. NUNCA excede el tamano original.
    Mide altura real renderizada, no textbbox (que incluye metricas).
    """
    if target_height < 8:
        target_height = 8

    lo = 6
    hi = target_height * 3
    best_size = target_height
    best_diff = 999999

    for _ in range(25):
        mid = (lo + hi) // 2
        if mid < 6:
            mid = 6
        try:
            font = ImageFont.truetype(font_path, mid)
        except:
            return best_size

        pixel_h, pixel_w = measure_rendered_pixel_height(font, new_text)

        if pixel_h == 0:
            lo = mid + 1
            continue

        diff = abs(pixel_h - target_height)

        if diff < best_diff:
            best_diff = diff
            best_size = mid

        if pixel_h < target_height:
            lo = mid + 1
        elif pixel_h > target_height:
            hi = mid - 1
        else:
            best_size = mid
            break

        if lo > hi:
            # Tambien verificar lo y hi directamente
            for candidate in [lo, max(6, hi)]:
                try:
                    fc = ImageFont.truetype(font_path, candidate)
                    ph, _ = measure_rendered_pixel_height(fc, new_text)
                    d = abs(ph - target_height)
                    if d < best_diff:
                        best_diff = d
                        best_size = candidate
                except:
                    pass
            break

    # Solo reducir si excede ancho - NUNCA aumentar
    if max_width and best_size > 6:
        try:
            font = ImageFont.truetype(font_path, best_size)
            _, pixel_w = measure_rendered_pixel_height(font, new_text)
            while pixel_w > max_width and best_size > 6:
                best_size -= 1
                font = ImageFont.truetype(font_path, best_size)
                _, pixel_w = measure_rendered_pixel_height(font, new_text)
        except:
            pass

    return max(6, best_size)

# =====================================================
# ANALISIS DE ESTILO
# =====================================================
def capture_text_style(img, det):
    """
    FUNCION MAESTRA: Captura el estilo EXACTO del texto original.
    Analiza color, tamano, peso (bold), tipo (serif/sans), fuente,
    posicion exacta y baseline - todo en un solo pase.
    
    El resultado se usa directamente por apply_edit para renderizar
    el texto nuevo con las mismas caracteristicas.
    """
    x, y, w, h = det['x'], det['y'], det['w'], det['h']
    text = det['text']
    H, W = img.shape[:2]

    # ===== 1. EXTRAER CROP Y MASCARA BINARIA =====
    pad = 4
    x1 = max(0, x - pad); y1 = max(0, y - pad)
    x2 = min(W, x + w + pad); y2 = min(H, y + h + pad)
    crop = img[y1:y2, x1:x2]
    if crop.size == 0:
        return default_style(w, h, x, y)

    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    h_c, w_c = gray.shape
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bg_mean = np.mean(gray[binary == 255]) if np.any(binary == 255) else 128
    text_mean = np.mean(gray[binary == 0]) if np.any(binary == 0) else 128

    if bg_mean > text_mean:
        text_mask = binary == 0
    else:
        text_mask = binary == 255

    # ===== 2. COLOR EXACTO (pixeles core, sin bordes anti-alias) =====
    text_pixels = crop[text_mask]
    if len(text_pixels) > 0:
        bg_pixels = crop[~text_mask]
        if len(bg_pixels) > 0:
            bg_color_arr = np.median(bg_pixels, axis=0)
            dists = np.sqrt(np.sum((text_pixels.astype(float) - bg_color_arr) ** 2, axis=1))
            threshold = np.percentile(dists, 80)
            core_pixels = text_pixels[dists >= threshold]
            if len(core_pixels) > 0:
                text_color_bgr = np.median(core_pixels, axis=0).astype(int)
            else:
                text_color_bgr = np.median(text_pixels, axis=0).astype(int)
        else:
            text_color_bgr = np.median(text_pixels, axis=0).astype(int)
    else:
        text_color_bgr = np.array([0, 0, 0])

    # ===== 3. MEDICION EXACTA DE DIMENSIONES =====
    row_sums = np.sum(text_mask, axis=1)
    col_sums = np.sum(text_mask, axis=0)
    text_rows = np.where(row_sums > 0)[0]
    text_cols = np.where(col_sums > 0)[0]

    if len(text_rows) > 0 and len(text_cols) > 0:
        actual_height = text_rows[-1] - text_rows[0] + 1
        actual_width = text_cols[-1] - text_cols[0] + 1
        tight_top = y1 + int(text_rows[0])
        tight_left = x1 + int(text_cols[0])
        tight_right = x1 + int(text_cols[-1]) + 1
        tight_bottom = y1 + int(text_rows[-1]) + 1
    else:
        actual_height = h
        actual_width = w
        tight_top = y
        tight_left = x
        tight_right = x + w
        tight_bottom = y + h

    # ===== 4. DETECCION DE PESO (BOLD) =====
    binary_uint8 = (text_mask * 255).astype(np.uint8)
    dist_transform = cv2.distanceTransform(binary_uint8, cv2.DIST_L2, 5)
    avg_stroke = 2 * np.median(dist_transform[text_mask]) if np.any(text_mask) else 1
    stroke_ratio = avg_stroke / max(actual_height, 1)
    fill_ratio = np.count_nonzero(text_mask) / max(text_mask.size, 1)
    is_bold = stroke_ratio > 0.13 or fill_ratio > 0.28

    # ===== 5. DETECCION DE TIPO (SERIF vs SANS) =====
    top_strip = text_mask[:max(2, h_c // 6), :]
    bottom_strip = text_mask[-max(2, h_c // 6):, :]
    top_density = np.sum(top_strip) / max(top_strip.size, 1)
    bottom_density = np.sum(bottom_strip) / max(bottom_strip.size, 1)
    mid_density = np.sum(text_mask[h_c//3:2*h_c//3, :]) / max(text_mask[h_c//3:2*h_c//3, :].size, 1)
    serif_score = (top_density + bottom_density) / max(2 * mid_density, 0.01)
    col_std = np.std(col_sums.astype(float)) / max(np.mean(col_sums.astype(float)), 1)
    is_serif = serif_score > 1.15 and col_std > 0.8

    # ===== 6. EXTRACCION DE CARACTERISTICAS DEL ORIGINAL =====
    orig_binary = binary_uint8[tight_top - y1:tight_bottom - y1,
                               tight_left - x1:tight_right - x1]
    if orig_binary.size == 0 or orig_binary.shape[0] < 2 or orig_binary.shape[1] < 2:
        orig_binary = binary_uint8
    orig_features = extract_font_features(orig_binary)
    orig_aspect = actual_width / max(actual_height, 1)

    logging.info(
        f"Estilo capturado: bold={is_bold} stroke_r={stroke_ratio:.3f} "
        f"fill={fill_ratio:.3f} serif={is_serif} h={actual_height}px w={actual_width}px "
        f"color_bgr=({text_color_bgr[0]},{text_color_bgr[1]},{text_color_bgr[2]})"
    )

    # ===== 7. MATCHING DE FUENTE CON TAMANO EXACTO =====
    best_font = match_font_exact(text, actual_height, actual_width,
                                 orig_binary, orig_features, orig_aspect,
                                 is_bold, is_serif)

    # ===== 8. BASELINE =====
    if len(text_rows) > 2:
        row_density = row_sums.astype(float)
        lower_start = len(row_density) * 2 // 3
        lower_section = row_density[lower_start:]
        if len(lower_section) > 0:
            baseline = y1 + lower_start + int(np.argmax(lower_section))
        else:
            baseline = tight_bottom
    else:
        baseline = tight_bottom

    style = {
        'color_bgr': tuple(int(c) for c in text_color_bgr),
        'actual_text_height': actual_height,
        'actual_text_width': actual_width,
        'is_bold': is_bold,
        'is_serif': is_serif,
        'fill_ratio': fill_ratio,
        'avg_stroke': avg_stroke,
        'stroke_ratio': stroke_ratio,
        'font_name': best_font['name'],
        'font_path': best_font['path'],
        'font_size': best_font['font_size'],
        'font_score': best_font['score'],
        'height': h,
        'width': w,
        'exact_pos': {
            'top': tight_top,
            'left': tight_left,
            'bottom': tight_bottom,
            'right': tight_right,
            'baseline': baseline,
            'center_x': (tight_left + tight_right) // 2,
            'center_y': (tight_top + tight_bottom) // 2,
            'width': tight_right - tight_left,
            'height': tight_bottom - tight_top,
        },
    }

    logging.info(
        f"Fuente: {best_font['name']} size={best_font['font_size']}px "
        f"score={best_font['score']:.3f}"
    )
    return style


def match_font_exact(text, target_height, target_width,
                     orig_binary, orig_features, orig_aspect,
                     is_bold, is_serif):
    """
    Para cada fuente del registro:
    1. Calcula el font_size exacto que produce target_height en pixeles
    2. Renderiza el texto a ese tamano
    3. Compara pixel a pixel (IoU) con el original
    4. Compara features y aspect ratio
    Devuelve la fuente con mejor score y SU tamano exacto ya calculado.
    """
    if target_height < 8:
        target_height = 8

    best_score = -1
    best_name = None
    best_path = None
    best_size = target_height
    all_scores = []

    for name, info in FONT_REGISTRY.items():
        try:
            font_path = info['path']
        except:
            continue

        # Calcular el font_size que produce target_height pixeles reales
        font_size = find_font_size_for_height(font_path, target_height, text)
        if font_size < 6:
            continue

        try:
            font = ImageFont.truetype(font_path, font_size)
        except:
            continue

        # Renderizar texto
        dummy = Image.new('L', (3000, 500), 0)
        dd = ImageDraw.Draw(dummy)
        bbox = dd.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw <= 0 or th <= 0:
            continue

        pil = Image.new('L', (tw + 40, th + 40), 0)
        draw = ImageDraw.Draw(pil)
        draw.text((20 - bbox[0], 20 - bbox[1]), text, fill=255, font=font)
        rendered = np.array(pil)

        # Medir tight bbox del render
        r_rows = np.where(np.any(rendered > 0, axis=1))[0]
        r_cols = np.where(np.any(rendered > 0, axis=0))[0]
        if len(r_rows) == 0 or len(r_cols) == 0:
            continue
        r_top, r_bottom = r_rows[0], r_rows[-1] + 1
        r_left, r_right = r_cols[0], r_cols[-1] + 1
        r_h = r_bottom - r_top
        r_w = r_right - r_left
        if r_h < 2 or r_w < 2:
            continue

        # Escalar al tamano exacto del original para comparar
        rendered_tight = rendered[r_top:r_bottom, r_left:r_right]
        oh, ow = orig_binary.shape
        rendered_scaled = cv2.resize(rendered_tight, (ow, oh),
                                     interpolation=cv2.INTER_AREA)
        rendered_bin = (rendered_scaled > 127).astype(np.uint8) * 255

        # IoU pixel a pixel
        intersection = np.sum((orig_binary > 0) & (rendered_bin > 0))
        union = np.sum((orig_binary > 0) | (rendered_bin > 0))
        iou = intersection / max(union, 1)

        # Features
        rend_features = extract_font_features(rendered_bin)
        feature_score = compare_features(orig_features, rend_features)

        # Aspect ratio del render vs original
        rend_aspect = r_w / max(r_h, 1)
        aspect_diff = abs(orig_aspect - rend_aspect) / max(orig_aspect, 0.01)
        aspect_score = max(0, 1 - aspect_diff)

        # Score: 55% IoU + 25% features + 20% aspect
        combined = 0.55 * iou + 0.25 * feature_score + 0.20 * aspect_score

        all_scores.append((name, combined, iou, feature_score, aspect_score, font_size))

        if combined > best_score:
            best_score = combined
            best_name = name
            best_path = font_path
            best_size = font_size

    if best_path is None:
        best_name = 'DejaVuSerif' if is_serif else 'DejaVuSans'
        best_path = SYS_FONTS.get(best_name, list(FONT_REGISTRY.values())[0]['path'])
        best_size = target_height
        best_score = 0

    # Log top 3
    all_scores.sort(key=lambda x: -x[1])
    for s in all_scores[:3]:
        logging.info(
            f"  {s[0]:30s} score={s[1]:.3f} iou={s[2]:.3f} "
            f"feat={s[3]:.3f} aspect={s[4]:.3f} size={s[5]}"
        )

    return {
        'name': best_name,
        'path': best_path,
        'font_size': best_size,
        'score': best_score,
    }


def find_font_size_for_height(font_path, target_pixel_height, text):
    """
    Binary search: encuentra el font_size (point size) que produce
    una altura de pixeles visibles igual a target_pixel_height.
    Usa measure_rendered_pixel_height para medir real, no textbbox.
    """
    if target_pixel_height < 8:
        target_pixel_height = 8

    lo = 6
    hi = target_pixel_height * 4
    best_size = target_pixel_height
    best_diff = 999999

    for _ in range(25):
        mid = (lo + hi) // 2
        if mid < 6:
            mid = 6
        try:
            font = ImageFont.truetype(font_path, mid)
        except:
            return best_size

        pixel_h, _ = measure_rendered_pixel_height(font, text)
        if pixel_h == 0:
            lo = mid + 1
            continue

        diff = abs(pixel_h - target_pixel_height)
        if diff < best_diff:
            best_diff = diff
            best_size = mid

        if pixel_h < target_pixel_height:
            lo = mid + 1
        elif pixel_h > target_pixel_height:
            hi = mid - 1
        else:
            best_size = mid
            break

        if lo > hi:
            for candidate in [lo, max(6, hi)]:
                try:
                    fc = ImageFont.truetype(font_path, candidate)
                    ph, _ = measure_rendered_pixel_height(fc, text)
                    d = abs(ph - target_pixel_height)
                    if d < best_diff:
                        best_diff = d
                        best_size = candidate
                except:
                    pass
            break

    return max(6, best_size)


def default_style(w, h, x=0, y=0):
    return {
        'color_bgr': (0, 0, 0),
        'actual_text_height': max(8, int(h * 0.72)),
        'actual_text_width': w,
        'is_bold': False, 'is_serif': False,
        'fill_ratio': 0, 'avg_stroke': 1, 'stroke_ratio': 0,
        'font_name': 'DejaVuSans',
        'font_path': FONT_REGISTRY.get('DejaVuSans', {}).get('path', SYS_FONTS['DejaVuSans']),
        'font_size': max(8, int(h * 0.72)),
        'font_score': 0,
        'height': h, 'width': w,
        'exact_pos': {
            'top': y, 'left': x, 'bottom': y + h, 'right': x + w,
            'baseline': y + int(h * 0.75),
            'center_x': x + w // 2, 'center_y': y + h // 2,
            'width': w, 'height': h,
        },
    }


def extract_font_features(binary_img):
    binary = binary_img > 0
    total = binary.size
    if total == 0 or np.count_nonzero(binary) == 0:
        return {'fill': 0, 'stroke': 0, 'col_var': 0, 'row_var': 0, 'edge_density': 0}
    h, w = binary_img.shape
    fill = np.count_nonzero(binary) / total
    dist = cv2.distanceTransform(binary_img.astype(np.uint8) * 255, cv2.DIST_L2, 5)
    stroke = np.median(dist[binary]) * 2 if np.any(binary) else 0
    col_sums = np.sum(binary, axis=0).astype(float)
    row_sums = np.sum(binary, axis=1).astype(float)
    col_var = np.std(col_sums) / max(np.mean(col_sums), 1)
    row_var = np.std(row_sums) / max(np.mean(row_sums), 1)
    edges = cv2.Canny(binary_img.astype(np.uint8) * 255, 30, 100)
    edge_density = np.count_nonzero(edges) / max(np.count_nonzero(binary), 1)
    return {'fill': fill, 'stroke': stroke / max(h, 1), 'col_var': col_var,
            'row_var': row_var, 'edge_density': edge_density}


def compare_features(f1, f2):
    keys = ['fill', 'stroke', 'col_var', 'row_var', 'edge_density']
    total_diff = 0
    for k in keys:
        v1, v2 = f1.get(k, 0), f2.get(k, 0)
        if v1 + v2 > 0:
            diff = abs(v1 - v2) / (v1 + v2)
        else:
            diff = 0
        total_diff += diff
    return max(0, 1 - (total_diff / len(keys)))


# =====================================================
# EDICION CON POSICIONAMIENTO Y TAMANO EXACTO
# =====================================================
def apply_edit(working_img, det, style, new_text):
    x, y, w, h = det['x'], det['y'], det['w'], det['h']

    # 1. Borrar texto con inpainting quirurgico
    erased = erase_text_precise(working_img, det)

    # 2. Obtener posicion y estilo exacto del texto original
    exact_pos = style.get('exact_pos', {})
    target_height = style.get('actual_text_height', h)
    target_top = exact_pos.get('top', y)
    target_left = exact_pos.get('left', x)
    target_baseline = exact_pos.get('baseline', y + int(h * 0.75))
    target_width = exact_pos.get('width', w)

    # 3. Usar la fuente elegida por capture_text_style,
    #    pero recalcular el tamano exacto para el texto NUEVO
    #    asi la altura de pixeles coincide sin importar mayusculas/minusculas
    font_path = style['font_path']
    max_w = int(target_width * 1.08)
    font_size = calculate_exact_font_size(font_path, target_height, new_text, max_w)
    font = ImageFont.truetype(font_path, font_size)

    # 4. Medir el texto nuevo renderizado
    pil_img = Image.fromarray(cv2.cvtColor(erased, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil_img)
    bbox = draw.textbbox((0, 0), new_text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    # 5. ===== POSICIONAMIENTO EXACTO =====
    # Alinear top-left del texto renderizado con top-left del texto original
    tx = target_left - bbox[0]
    ty = target_top - bbox[1]

    # Ajuste fino de baseline: si las metricas internas difieren,
    # alinear por baseline
    rendered_bottom = bbox[3]
    original_bottom_offset = target_baseline - target_top
    if abs(rendered_bottom - original_bottom_offset) > 3:
        ty = target_baseline - rendered_bottom

    color_rgb = (style['color_bgr'][2], style['color_bgr'][1], style['color_bgr'][0])
    draw.text((tx, ty), new_text, fill=color_rgb, font=font)

    return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

# =====================================================
# PROCESAMIENTO DE MENSAJES
# =====================================================
def process_message(message):
    try:
        user_id = message.from_user.id
        chat_id = message.chat.id
        text = message.text
        logging.info(f"MSG from {user_id}: {text[:50] if text else '[photo]'}")

        if text and text.startswith('/start') or text and text.startswith('/help'):
            reset_session(user_id)
            safe_send(chat_id,
                "🎨 <b>Editor de Plantillas v7</b>\n\n"
                "<b>Flujo:</b>\n"
                "1. Sube la foto de tu plantilla\n"
                "2. Detecto todos los textos y te los numero\n"
                "3. Elige el numero del texto a editar\n"
                "4. Analizo el estilo original y lo clono\n"
                "5. Escribe el texto nuevo\n"
                "6. Vuelvo a preguntar — edita otro o escribe <b>listo</b>\n"
                "7. Al escribir <b>listo</b> recibes la plantilla final\n\n"
                "/cancel - Empezar de nuevo\n"
                "/manual - Borrar por coordenadas",
                parse_mode='HTML')
            return

        if text and text.startswith('/cancel'):
            reset_session(user_id)
            safe_send(chat_id, "✅ Cancelado. Sube una nueva plantilla.")
            return

        if text and text.startswith('/manual'):
            sess = get_session(user_id)
            if not sess['working_path']:
                safe_send(chat_id, "Primero sube una foto de plantilla.")
                return
            sess['state'] = 'manual_coords'
            safe_send(chat_id, "Modo manual:\nEnvia coordenadas: <code>x,y,ancho,alto</code>\nEjemplo: <code>100,200,300,50</code>", parse_mode='HTML')
            return

        if message.photo:
            handle_photo(message, user_id, chat_id)
            return

        sess = get_session(user_id)
        state = sess['state']

        if state == 'idle':
            safe_send(chat_id, "Sube una foto de plantilla. /help para instrucciones.")
            return

        if state == 'manual_coords':
            try:
                parts = text.strip().split(',')
                if len(parts) != 4: raise ValueError()
                mx, my, mw, mh = [int(p.strip()) for p in parts]
            except (ValueError, AttributeError):
                safe_send(chat_id, "Formato: <code>x,y,ancho,alto</code>\nEj: <code>100,200,300,50</code>", parse_mode='HTML')
                return
            det = {
                'bbox': [[mx, my], [mx+mw, my], [mx+mw, my+mh], [mx, my+mh]],
                'text': '', 'conf': 1.0, 'x': mx, 'y': my, 'w': mw, 'h': mh,
                'style': default_style(mw, mh, mx, my),
            }
            sess['detections'] = [det]
            sess['selected'] = 0
            sess['state'] = 'typing'
            safe_send(chat_id, "Area seleccionada. Escribe el texto nuevo:")
            return

        if state == 'selecting':
            handle_selection(message, user_id, chat_id)
            return

        if state == 'typing':
            handle_new_text(message, user_id, chat_id)
            return

        safe_send(chat_id, "Sube una foto de plantilla. /help para instrucciones.")

    except Exception as e:
        logging.error(f"process_message error: {e}\n{traceback.format_exc()}")
        try:
            safe_send(message.chat.id, "❌ Error procesando. Usa /cancel y sube la foto de nuevo.")
        except:
            pass

def handle_photo(message, user_id, chat_id):
    reset_session(user_id)
    sess = get_session(user_id)
    safe_send(chat_id, "📸 Foto recibida. Detectando textos...")

    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded = bot.download_file(file_info.file_path)
    except Exception as e:
        logging.error(f"Error downloading photo: {e}")
        safe_send(chat_id, "❌ Error descargando la foto. Intenta de nuevo.")
        return

    original_path = os.path.join(UPLOAD_DIR, f'{user_id}_original.png')
    working_path = os.path.join(UPLOAD_DIR, f'{user_id}_working.png')
    with open(original_path, 'wb') as f: f.write(downloaded)
    with open(working_path, 'wb') as f: f.write(downloaded)
    sess['original_path'] = original_path
    sess['working_path'] = working_path

    try:
        ocr = get_ocr()
        results = ocr.readtext(original_path)
    except Exception as e:
        logging.error(f"OCR error: {e}")
        safe_send(chat_id, "❌ Error en OCR. Usa /manual")
        return

    if not results:
        safe_send(chat_id, "No detecte texto. Usa /manual para borrar por coordenadas.")
        return

    detections = []
    for (bbox, ocr_text, conf) in results:
        if conf < 0.25 or not ocr_text.strip(): continue
        pts = np.array(bbox, dtype=np.int32)
        x_min, y_min = pts[:, 0].min(), pts[:, 1].min()
        x_max, y_max = pts[:, 0].max(), pts[:, 1].max()
        dw = x_max - x_min; dh = y_max - y_min
        if dw < 5 or dh < 5: continue
        detections.append({
            'bbox': bbox, 'text': ocr_text.strip(), 'conf': conf,
            'x': int(x_min), 'y': int(y_min), 'w': int(dw), 'h': int(dh),
            'style': None,
        })

    if not detections:
        safe_send(chat_id, "No detecte texto valido. Usa /manual.")
        return

    sess['detections'] = detections
    sess['state'] = 'selecting'
    sess['edited'] = set()
    send_annotated_image(chat_id, sess, user_id)

def send_annotated_image(chat_id, sess, user_id):
    try:
        img = cv2.imread(sess['working_path'])
        detections = sess['detections']
        edited = sess['edited']
        img_ann = img.copy()
        available = []
        for i, det in enumerate(detections):
            if i in edited: continue
            available.append(i)
            pts = np.array(det['bbox'], dtype=np.int32)
            cv2.polylines(img_ann, [pts], True, (0, 255, 255), 3)
            cx, cy = int(pts[:, 0].mean()), int(pts[:, 1].mean())
            cv2.circle(img_ann, (cx, cy), 25, (0, 0, 0), -1)
            cv2.circle(img_ann, (cx, cy), 22, (0, 255, 255), 2)
            cv2.putText(img_ann, str(len(available)), (cx - 8, cy + 8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        ann_path = os.path.join(UPLOAD_DIR, f'{user_id}_ann.png')
        cv2.imwrite(ann_path, img_ann)
        text_list = "🔍 <b>Textos detectados:</b>\n\n"
        for idx, i in enumerate(available):
            det = detections[i]
            preview = det['text'][:40] + ('...' if len(det['text']) > 40 else '')
            text_list += f"<b>{idx + 1}.</b> {preview}\n"
        if edited:
            text_list += f"\n✅ {len(edited)} texto(s) editado(s)"
        text_list += f"\n\nManda el <b>numero</b> a editar o escribe <b>listo</b>"
        with open(ann_path, 'rb') as f:
            safe_send_photo(chat_id, f, caption=text_list, parse_mode='HTML')
        os.unlink(ann_path)
        sess['available_indices'] = available
    except Exception as e:
        logging.error(f"Error in send_annotated_image: {e}\n{traceback.format_exc()}")
        safe_send(chat_id, "❌ Error generando imagen. Intenta /cancel y sube la foto de nuevo.")

def handle_selection(message, user_id, chat_id):
    sess = get_session(user_id)
    text = message.text.strip().lower()

    if text in ('listo', 'done', 'fin', 'terminar', 'ya'):
        if not sess['edited']:
            safe_send(chat_id, "No has editado nada. Manda un numero o /cancel.")
            return
        send_final_image(chat_id, sess, user_id)
        reset_session(user_id)
        return

    try:
        num = int(text)
    except ValueError:
        safe_send(chat_id, "Manda el <b>numero</b> o escribe <b>listo</b>", parse_mode='HTML')
        return

    available = sess.get('available_indices', [])
    if num < 1 or num > len(available):
        safe_send(chat_id, f"Numero invalido. Elige 1-{len(available)}.")
        return

    real_idx = available[num - 1]
    sess['selected'] = real_idx
    det = sess['detections'][real_idx]
    safe_send(chat_id, f"🔬 Analizando estilo del texto \"{det['text'][:40]}\"...")

    try:
        img = cv2.imread(sess['original_path'])
        style = capture_text_style(img, det)
        det['style'] = style
    except Exception as e:
        logging.error(f"Error analizando estilo: {e}\n{traceback.format_exc()}")
        det['style'] = default_style(det['w'], det['h'], det['x'], det['y'])

    sess['state'] = 'typing'
    s = det['style']
    color = s.get('color_bgr', (0, 0, 0))
    pos = s.get('exact_pos', {})
    safe_send(chat_id,
        f"✅ Zona {num}: \"{det['text'][:50]}\"\n\n"
        f"🎨 <i>Estilo clonado:</i>\n"
        f"   Fuente: {s.get('font_name', '?')} (size {s.get('font_size', '?')}px)\n"
        f"   Altura real: {s.get('actual_text_height', '?')}px\n"
        f"   Negrita: {'Si' if s.get('is_bold') else 'No'}\n"
        f"   Color RGB: ({color[2]}, {color[1]}, {color[0]})\n"
        f"   Pos: top={pos.get('top','?')} left={pos.get('left','?')}\n\n"
        f"Escribe el texto nuevo:",
        parse_mode='HTML')

def handle_new_text(message, user_id, chat_id):
    sess = get_session(user_id)
    new_text = message.text.strip()

    if not new_text:
        safe_send(chat_id, "El texto no puede estar vacio.")
        return

    safe_send(chat_id, "🎨 Aplicando edicion...")

    try:
        idx = sess['selected']
        det = sess['detections'][idx]
        style = det.get('style') or default_style(det['w'], det['h'], det['x'], det['y'])
        working_img = cv2.imread(sess['working_path'])
        result = apply_edit(working_img, det, style, new_text)
        cv2.imwrite(sess['working_path'], result)
        sess['edited'].add(idx)
        sess['state'] = 'selecting'
        logging.info(f"Edit OK: '{new_text[:30]}' at ({det['x']},{det['y']}) height={style.get('actual_text_height','?')}px")
        safe_send(chat_id, f"✅ Reemplazado: \"{new_text[:40]}\"\n¿Otro? Manda el numero o <b>listo</b>", parse_mode='HTML')
        send_annotated_image(chat_id, sess, user_id)
    except Exception as e:
        logging.error(f"Error editando: {e}\n{traceback.format_exc()}")
        safe_send(chat_id, "❌ Error editando. Intenta de nuevo o /cancel.")
        sess['state'] = 'selecting'

def send_final_image(chat_id, sess, user_id):
    try:
        with open(sess['working_path'], 'rb') as f:
            safe_send_document(chat_id, f, caption="✅ ¡Plantilla lista!\n<i>Ediciones con estilo clonado y posicionamiento preciso.</i>", parse_mode='HTML')
    except Exception as e:
        logging.error(f"Error sending final: {e}")
        safe_send(chat_id, "❌ Error enviando plantilla final. Intenta /cancel.")

# =====================================================
# POLLING MANUAL - Imposible quedarse zombie
# =====================================================
def run_bot():
    if not BOT_TOKEN:
        print("ERROR: No hay TELEGRAM_BOT_TOKEN en variables de entorno")
        return

    logging.info("Pre-cargando OCR...")
    get_ocr()
    logging.info("OCR listo. Iniciando bot v7 con polling manual...")

    last_update_id = 0

    while True:
        try:
            updates = bot.get_updates(offset=last_update_id, timeout=25, long_polling_timeout=25)
            if updates:
                for update in updates:
                    last_update_id = update.update_id + 1
                    if update.message:
                        process_message(update.message)
        except Exception as e:
            logging.error(f"Polling error: {e}")
            logging.info("Reintentando en 3 segundos...")
            time.sleep(3)

if __name__ == '__main__':
    run_bot()
