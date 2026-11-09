"""Düzenleme modüllerinin (editor, kisisel_veri, paragraflar) ortak küçük yardımcıları: ekran koordinatıyla
(sayfanın göründüğü hâliyle, 0–1 arası) PDF koordinatı arasında çevirme, yazı yönünden döndürme açısı, gömülen
yazı tipinin PDF'teki adı."""
import hashlib

import pymupdf


def _disp_rect(page, item):
    W, H = page.rect.width, page.rect.height
    r = pymupdf.Rect(item["x"] * W, item["y"] * H, (item["x"] + item["w"]) * W, (item["y"] + item["h"]) * H)
    return r.normalize()


def _native(page, rect):
    return (rect * page.derotation_matrix).normalize()


def _fname(path):
    return "PSF" + hashlib.md5(str(path).encode()).hexdigest()[:6]


DIR_ROTATE = {(1, 0): 0, (0, -1): 90, (-1, 0): 180, (0, 1): 270}


def _dir_rotate(direction):
    return DIR_ROTATE.get((round(direction[0]), round(direction[1])), 0)
