from __future__ import annotations

import math
from concurrent.futures import CancelledError
from functools import lru_cache

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from .pixels import (
    _bbox, _binary_mask, _crop_mask, _point_lut, _template_font_indexes,
    _template_fonts, _threshold_lut,
)
from .recognition import (
    _consensus_numeric_reading, _gray_difference, _independent_word_candidates,
    _ocr_numeric, _read_fast_independent_word, _read_independent_word,
    _read_probe_word, _sized_template_font, _word_template_score,
)
from .shared import _SOURCE_OCR_CANCEL

@lru_cache(maxsize=512)
def _gray_contrast_lut(low, high):
    scale = 255.0 / (high - low)
    offset = -low * scale
    return bytes(max(0, min(255, int(value * scale + offset))) for value in range(256))


def _autocontrast_gray(gray):
    # ImageOps.autocontrast rebuilds/scans a 256-entry LUT for every template.
    # Most rendered font rasters already span 0..255 and require no operation.
    low, high = gray.getextrema()
    if (low == 0 and high == 255) or low == high:
        return gray
    return _point_lut(gray, _gray_contrast_lut(low, high))


def _normalized_gray_word(gray, *, light=None):
    if light is None:
        histogram = gray.histogram()
        light = max(range(256), key=lambda v: histogram[v]) >= 128
    ink = _autocontrast_gray(ImageChops.invert(gray) if light else gray)
    bounds = _point_lut(ink, _threshold_lut(48, dark=False, peak=255)).getbbox()
    if bounds is None:
        return None
    ink = ink.crop(bounds)
    return ink.resize((max(1, round(ink.width * 28 / ink.height)), 28), Image.Resampling.BILINEAR)


@lru_cache(maxsize=256)
def _rotated_gray_templates(text, height, orientation, font_hint=None):
    templates = []
    size = max(8, min(32, round(height / .72)))
    for index, font in enumerate(_template_fonts()):
        if index not in (0, 1, 5, 6, 7):
            continue
        if font_hint is not None and index != font_hint:
            continue
        for points in range(max(7, size - 2), size + 2):
            variant = _sized_template_font(index, points)
            box = variant.getbbox(text)
            gray = Image.new('L', (max(1, box[2] - box[0] + 8), max(1, box[3] - box[1] + 8)), 255)
            ImageDraw.Draw(gray).text((4 - box[0], 4 - box[1]), text, font=variant, fill=0)
            gray = gray.rotate(-orientation, expand=True, fillcolor=255,
                               resample=Image.Resampling.BICUBIC if orientation % 90 else Image.Resampling.NEAREST)
            template = _normalized_gray_word(gray, light=True)
            if template is not None:
                templates.append(template)
    return tuple(templates)


def _rotated_gray_score(observed, text, height, orientation, *, font_hint=None):
    best = 1.0
    for template in _rotated_gray_templates(text, height, orientation, font_hint):
        penalty = .05 * abs(math.log(observed.width / template.width))
        reference = template.resize(observed.size, Image.Resampling.BILINEAR)
        error = _gray_difference(observed, reference)
        best = min(best, error + penalty)
    return best


def _compressed_gray_score(observed, text, height, *, font_hint=None):
    best = 1.0
    # Reproduce lost raster detail BEFORE comparing at the normalized size.
    # Comparing a sharp font against an enlarged 6 px glyph confuses 2/7, 5/6.
    for template in _rotated_gray_templates(text, 12, 0, font_hint):
        penalty = .05 * abs(math.log(observed.width / template.width))
        for raster_height in (height, height + 1):
            low = template.resize((max(1, round(observed.width * raster_height / 28)), raster_height),
                                  Image.Resampling.BICUBIC)
            reference = _autocontrast_gray(low).resize(observed.size, Image.Resampling.BILINEAR)
            error = _gray_difference(observed, reference)
            best = min(best, error + penalty)
    return best


@lru_cache(maxsize=512)
def _small_source_font_rasters(text, index):
    """Cache each face separately so hinted fits render no unrelated fonts."""
    if not 0 <= index < len(_template_fonts()):
        return ()
    rasters = []
    for size in (14, 16, 18):
        font = _sized_template_font(index, size)
        box = font.getbbox(text)
        width, height = max(1, box[2] - box[0]), max(1, box[3] - box[1])
        raster = Image.new('L', (width + 8, height + 8), 255)
        ImageDraw.Draw(raster).text((4 - box[0], 4 - box[1]), text, font=font, fill=0)
        rasters.append((index, raster, width, height))
    return tuple(rasters)


def _small_source_rasters(text, font_hint=None):
    """Uncompressed font rasters; keep padding for subpixel downsampling."""
    indexes = _template_font_indexes()
    if font_hint is not None and font_hint not in indexes:
        font_hint = None
    return tuple(raster for index in indexes
                 if font_hint is None or index == font_hint
                 for raster in _small_source_font_rasters(text, index))


def _phase_raster_score(observed, source_width, height, text):
    return _phase_raster_fit(observed, source_width, height, text)[0]


def _phase_raster_fit(observed, source_width, height, text, *, font_hint=None):
    """Model screenshot resampling phase, not just the final glyph height.

    A half-pixel shift before vertical compression can erase the upper stroke
    of a 2 or close a 5. Resize the padded original raster before cropping it.
    """
    best = 1.0
    best_font = None
    for font_index, raster, glyph_width, glyph_height in _small_source_rasters(text, font_hint):
        width = max(1, round(raster.width * source_width / glyph_width))
        heights = {max(1, round(raster.height * (height + delta) / glyph_height))
                   for delta in (-.5, 0, .5)}
        for offset in (-1, 0, 1, 2):
            shifted = ImageChops.offset(raster, 0, offset) if offset else raster
            for target_height in heights:
                low = shifted.resize((width, target_height), Image.Resampling.BICUBIC)
                reference = _normalized_gray_word(low, light=True)
                if reference is None:
                    continue
                penalty = .05 * abs(math.log(observed.width / reference.width))
                reference = reference.resize(observed.size, Image.Resampling.BILINEAR)
                error = _gray_difference(observed, reference)
                if error + penalty < best:
                    best, best_font = error + penalty, font_index
    return best, best_font


def _blurred_source_fit(observed, text, source_height):
    """Compare against fonts downsampled and blurred before normalization."""
    best, face = 1.0, None
    for font_index, raster, glyph_width, glyph_height in _small_source_rasters(text):
        _check_tick_cancelled(_SOURCE_OCR_CANCEL.get())
        for glyph_target_height in (max(3, source_height - 3), max(3, source_height - 2),
                                    max(3, source_height - 1)):
            sy = glyph_target_height / glyph_height
            for stretch in (.9, 1., 1.1):
                size = (max(1, round(raster.width * sy * stretch)),
                        max(1, round(raster.height * sy)))
                for offset in (0, 1):
                    shifted = ImageChops.offset(raster, 0, offset) if offset else raster
                    small = shifted.resize(size, Image.Resampling.BILINEAR)
                    for radius in (.5, .7, .9):
                        reference = _normalized_gray_word(small.filter(ImageFilter.GaussianBlur(radius)), light=True)
                        if reference is None:
                            continue
                        penalty = .08 * abs(math.log(observed.width / reference.width))
                        error = _gray_difference(observed, reference.resize(observed.size, Image.Resampling.BILINEAR))
                        if error + penalty < best:
                            best, face = error + penalty, font_index
    return best, face


def _read_small_source_word(image, bbox, mask, *, font_hint=None, with_profile=False):
    """Recover a compressed word from grayscale, before trying brighter masks."""
    # At 5-6 px, compression phase can resemble a different face on every
    # word. Reusing a face there can turn a printed 2000 into 2008.
    if len(mask) < 7:
        font_hint = None
    gray = image.crop((max(0, bbox[0] - 1), max(0, bbox[1] - 2),
                       min(image.width, bbox[2] + 2), min(image.height, bbox[3] + 3))).convert('L')
    args = (gray.width, gray.height, gray.tobytes(), len(mask[0]), len(mask), b''.join(mask))
    result = _cached_small_source_word(*args, font_hint)
    if result is None and font_hint is not None:
        result = _cached_small_source_word(*args, None)
    return result if with_profile or result is None else result[:3]


@lru_cache(maxsize=1024)
def _cached_upscaled_source_word(width, height, pixels, scale):
    """Cheap tiny-label recovery before the expensive font/raster search.

    Small screenshot labels often lose one horizontal stroke or a decimal at
    their native 6-10 px height. Bicubic enlargement restores enough grayscale
    separation for the existing independent OCR while remaining sub-millisecond
    for a normal tick word. No neighbouring tick values are used here.
    """
    gray = Image.frombytes('L', (width, height), pixels)
    enlarged = gray.resize((width * scale, height * scale), Image.Resampling.BICUBIC)
    return _read_fast_independent_word(_binary_mask(enlarged))


@lru_cache(maxsize=1024)
def _cached_blurred_source_word(width, height, pixels, scale=3):
    """Recover one blurred/low-contrast numeric label from its own pixels.

    This path is deliberately bounded and is used only after ordinary OCR has
    failed.  It never receives neighbouring values or an axis model.
    """
    gray = Image.frombytes('L', (width, height), pixels)
    if width <= 0 or height <= 0:
        return None
    enlarged = gray.resize((max(1, width * scale), max(1, height * scale)),
                           Image.Resampling.LANCZOS)
    variants = [enlarged]
    # Mild local sharpening restores strokes lost by screenshot scaling/JPEG
    # blur without inventing high-frequency edges on already-clean labels.
    variants.append(enlarged.filter(ImageFilter.UnsharpMask(radius=1.15, percent=170, threshold=2)))
    contrast = _autocontrast_gray(enlarged)
    variants.append(contrast.filter(ImageFilter.UnsharpMask(radius=.9, percent=135, threshold=1)))
    readings = []
    seen = set()
    for variant in variants:
        mask = _binary_mask(variant)
        signature = (len(mask), len(mask[0]) if mask else 0, b''.join(mask))
        if signature in seen:
            continue
        seen.add(signature)
        reading = _read_fast_independent_word(mask)
        if reading is not None and reading[2] >= .48:
            readings.append(reading)
    if not readings:
        return None
    consensus = _consensus_numeric_reading(readings)
    if consensus is not None and consensus[2] >= .50:
        return consensus
    return max(readings, key=lambda item: item[2]) if max(r[2] for r in readings) >= .66 else None


def _read_blurred_source_word(image, bbox, *, scale=3):
    # Expand slightly so blur halos at the glyph edge remain available.
    gray = image.crop((max(0, bbox[0] - 2), max(0, bbox[1] - 2),
                       min(image.width, bbox[2] + 3), min(image.height, bbox[3] + 3))).convert('L')
    if gray.width <= 0 or gray.height <= 0:
        return None
    return _cached_blurred_source_word(gray.width, gray.height, gray.tobytes(), scale)


def _deoccluded_colored_word_mask(image, bbox):
    """Neutralize colored overlays on one otherwise neutral label.

    Chart text is normally gray/black while Smart Region guides and plotted
    curves are colored. Translucent overlays retain neutral intensity changes
    from the underlying text; flat opaque pixels cannot recover that evidence.
    The repaired raster is verified independently by OCR/template matching.
    """
    box = (max(0, bbox[0] - 1), max(0, bbox[1] - 1),
           min(image.width, bbox[2] + 2), min(image.height, bbox[3] + 2))
    crop = image.crop(box).convert('RGB')
    if crop.width <= 0 or crop.height <= 0:
        return None
    # Estimate the local background from the dominant luminance.
    gray = crop.convert('L')
    histogram = gray.histogram()
    background = max(range(256), key=lambda value: histogram[value])
    rgb = crop.load()
    overlay = Image.new('L', crop.size, 0)
    out = overlay.load()
    colored = 0
    references = {}
    colored_pixels = []
    for y in range(crop.height):
        for x in range(crop.width):
            r, g, b = rgb[x, y]
            chroma = max(r, g, b) - min(r, g, b)
            # Require both real chroma and enough contrast from the local
            # background. Antialiased gray text remains untouched.
            luminance = (299 * r + 587 * g + 114 * b) // 1000
            if chroma >= 12 and abs(luminance - background) >= 6:
                out[x, y] = 255
                colored += 1
                low, high = min(r, g, b), max(r, g, b)
                # Alpha compositing a colored guide over neutral ink preserves
                # channel differences. Compare only pixels with that same tint.
                key = tuple(round((value - low) / 8) for value in (r, g, b))
                colored_pixels.append((x, y, key, high))
                if key not in references or high > references[key][0]:
                    references[key] = (high, low)
    if colored < max(2, round(crop.width * crop.height * .004)):
        return None
    # Do not dilate into neutral glyphs: a one-pixel guide over a tiny zero
    # would otherwise erase three columns and open its bowl completely.
    repaired = gray.copy()
    repaired.paste(background, mask=overlay)
    if background >= 128:
        restored = repaired.load()
        for x, y, key, high in colored_pixels:
            reference_high, reference_low = references[key]
            # A translucent stroke still contains measurable underlying text.
            # Restore its neutral contrast instead of erasing it. Opaque flat
            # strokes have zero difference and remain blank/unread, not guessed.
            transmission = max(.125, min(1.0, reference_low / max(1.0, background)))
            difference = max(0, reference_high - high)
            restored[x, y] = max(0, min(255, round(background - difference / transmission)))
    mask = _binary_mask(repaired)
    bounds = _bbox(mask)
    return _crop_mask(mask, bounds) if bounds is not None else None


def _read_deoccluded_colored_word(image, bbox):
    mask = _deoccluded_colored_word_mask(image, bbox)
    if mask is None:
        return None
    choices = []
    probe = _read_probe_word(mask)
    if probe is not None:
        choices.append(probe)
    if probe is None or probe[2] < .68:
        exact = _read_fast_independent_word(mask)
        if exact is not None:
            choices.append(exact)
    result = _consensus_numeric_reading(choices)
    if result is None or result[2] < .56:
        return None
    return result


def _read_upscaled_source_word(image, bbox, *, scale=3):
    gray = image.crop((max(0, bbox[0] - 1), max(0, bbox[1] - 1),
                       min(image.width, bbox[2] + 2), min(image.height, bbox[3] + 2))).convert('L')
    if gray.width <= 0 or gray.height <= 0:
        return None
    return _cached_upscaled_source_word(gray.width, gray.height, gray.tobytes(), scale)


@lru_cache(maxsize=512)
def _cached_small_source_word(width, height, pixels, mask_width, mask_height, mask_pixels, font_hint=None):
    gray = Image.frombytes('L', (width, height), pixels)
    mask = [bytearray(mask_pixels[y * mask_width:(y + 1) * mask_width]) for y in range(mask_height)]
    observed = _normalized_gray_word(gray)
    if observed is None:
        return None
    candidates = {}
    required = set()
    masks = [mask]
    histogram = gray.histogram()
    light = max(range(256), key=lambda v: histogram[v]) >= 128
    for threshold in (193, 215, 235, 245):
        ink = gray.point([int(v <= threshold) if light else int(v >= 255 - threshold) for v in range(256)])
        data = ink.tobytes()
        masks.append([bytearray(data[y * ink.width:(y + 1) * ink.width]) for y in range(ink.height)])
    # A native segmentation can recover a faint word that the beam misses, but
    # a single threshold can also turn a damaged digit into a convincing wrong
    # value. Only promote native readings that repeat across at least two
    # *different* thresholds. This preserves faint labels such as 12000 without
    # allowing one accidental 3.0 to override the surrounding image evidence.
    native_votes = {}
    for candidate_mask in masks:
        native = _ocr_numeric(candidate_mask)
        if native is not None:
            text, value, confidence = native
            entries = native_votes.setdefault(text, [])
            entries.append((value, confidence))
    hypotheses = [(candidate_mask, 1.0) for candidate_mask in masks] + [(masks[-1], 1.5)]
    for candidate_mask, width_multiplier in hypotheses:
        native = _ocr_numeric(candidate_mask)
        if native is not None and len(native_votes.get(native[0], ())) >= 2:
            text, value, confidence = native
            native_error = (1.0 - confidence) * .6
            previous = candidates.get(text)
            candidates[text] = (value, min(native_error, previous[1]) if previous else native_error)
            if confidence >= .62:
                required.add(text)
        words = _independent_word_candidates(candidate_mask, width_multiplier=width_multiplier)
        required.update(text for text, _, _ in words[:1])
        for text, value, error in words:
            previous = candidates.get(text)
            candidates[text] = (value, min(error, previous[1]) if previous else error)
            # A broken serif stroke can be mistaken for a decimal point. This
            # is only another image hypothesis; grayscale must distinguish it.
            if '.' in text[1:] and sum(char.isdigit() for char in text) >= 4:
                plain = text.replace('.', '')
                candidates.setdefault(plain, (float(plain), error + .01))
                if text in required:
                    required.add(plain)
    if not candidates:
        return None
    height = len(mask)
    # Wide, short digits indicate a vertically compressed screenshot, not a
    # naturally tiny font. Compare against its pre-compression raster size.
    def image_score(text):
        digits = sum(char.isdigit() for char in text)
        compressed = len(mask[0]) / max(1, digits * height) >= .85
        return (_compressed_gray_score(observed, text, height, font_hint=font_hint) if compressed else
                min(_rotated_gray_score(observed, text, h, 0, font_hint=font_hint) for h in (height, 12)))
    ranked = []
    # Retain the best reading from EVERY threshold/segmentation. A broken
    # low-threshold glyph must not crowd all brighter hypotheses out of the beam.
    ordered_all = sorted(candidates.items(), key=lambda item: (item[0] not in required, item[1][1]))
    ordered = ordered_all[:6]
    # Keep a small number of threshold-voted hypotheses even if their glyph
    # beam score is slightly worse.  Six-to-eight grayscale comparisons are
    # enough to decide whether the source contains usable evidence; rendering
    # sixteen arbitrary strings was a major cold-start cost on cluttered axes.
    selected = {text for text, _ in ordered}
    for item in ordered_all[6:]:
        if item[0] in required and item[0] not in selected:
            ordered.append(item)
            selected.add(item[0])
        if len(ordered) >= 8:
            break
    # Low-contrast tiny labels can lose their decimal entirely in every binary
    # mask. Compare locally generated spellings against a raster that models
    # both downsampling and blur. The axis values/step are not inputs here.
    light_gray = gray if light else ImageChops.invert(gray)
    darkest, _ = light_gray.getextrema()
    if height <= 8 and mask_width / max(1, height) < 3 and 140 <= darkest <= 225:
        ink = _autocontrast_gray(ImageChops.invert(light_gray))
        bounds = _point_lut(ink, _threshold_lut(48, dark=False, peak=255)).getbbox()
        if bounds is not None:
            spellings = set()
            seeds = [text for text, _ in ordered]
            seeds.extend(text for text, _, _ in _independent_word_candidates(mask)[:4])
            for seed in dict.fromkeys(seeds):
                sign = '-' if seed.startswith('-') else ''
                digits = seed.lstrip('+-').replace('.', '')
                if not digits.isdigit() or len(digits) > 3:
                    continue
                spellings.add(seed)
                spellings.add(sign + digits)
                for split in range(1, len(digits)):
                    spellings.add(sign + digits[:split] + '.' + digits[split:])
            fits = []
            for spelling in sorted(spellings):
                error, face = _blurred_source_fit(observed, spelling, bounds[3] - bounds[1])
                fits.append((error, spelling, float(spelling), face))
            fits.sort()
            if fits:
                error, spelling, number, face = fits[0]
                runner = next((score for score, _, other, _ in fits[1:] if other != number), 1.)
                if error <= .105 and runner - error >= .008:
                    return spelling, number, min(.98, 1.0 - 1.7 * error), face
    for text, (value, _) in ordered:
        ranked.append((image_score(text), text, value))
    ranked.sort()
    # At 5-8 px, the right digit can fall outside the binary glyph beam. Verify
    # common shape confusions against the SAME source word, not axis values.
    if ranked[0][0] < .22:
        text = ranked[0][1]
        confusions = {'0': '689', '1': '57', '2': '37', '3': '258', '4': '9',
                      '5': '168', '6': '058', '7': '12', '8': '013569', '9': '0468'}
        seen = {s for _, s, _ in ranked}
        for index, char in enumerate(text[:10]):
            for replacement in confusions.get(char, ''):
                alternative = text[:index] + replacement + text[index + 1:]
                if alternative not in seen:
                    seen.add(alternative)
                    ranked.append((image_score(alternative), alternative, float(alternative)))
        ranked.sort()
    score, text, value = ranked[0]
    second = next((s for s, _, other in ranked[1:] if other != value), 1.0)
    limit, margin = (.14, .012) if font_hint is not None else (.22, .007)
    if score > limit or second - score < margin:
        if height <= 8 and score < .28:
            ink = _autocontrast_gray(ImageChops.invert(gray) if light else gray)
            bounds = _point_lut(ink, _threshold_lut(48, dark=False, peak=255)).getbbox()
            if bounds is not None:
                source_width = bounds[2] - bounds[0]
                phase_candidates = list(ranked[:6])
                selected = {s for _, s, _ in phase_candidates}
                for candidate in ranked[6:]:
                    if candidate[1] in required and candidate[1] not in selected and candidate[0] < .25:
                        phase_candidates.append(candidate)
                        selected.add(candidate[1])
                    if len(phase_candidates) >= 12:
                        break
                # Identify font appearance once for this word, then compare the
                # other readings in that same face. If the fit is weak or tied,
                # fall back to the complete multi-font search as before.
                first_text, first_value = phase_candidates[0][1:]
                first_score, local_hint = _phase_raster_fit(observed, source_width, height, first_text, font_hint=font_hint)
                refined = [(first_score, first_text, first_value, local_hint)]
                for _, s, v in phase_candidates[1:]:
                    error, face = _phase_raster_fit(observed, source_width, height, s, font_hint=local_hint)
                    refined.append((error, s, v, face))
                refined.sort()
                score, text, value, face = refined[0]
                second = next((s for s, _, other, _ in refined[1:] if other != value), 1.0)
                if font_hint is None and (score >= .12 or second - score < .006):
                    refined = []
                    for _, s, v in phase_candidates:
                        error, candidate_face = _phase_raster_fit(observed, source_width, height, s)
                        refined.append((error, s, v, candidate_face))
                    refined.sort()
                    score, text, value, face = refined[0]
                    second = next((s for s, _, other, _ in refined[1:] if other != value), 1.0)
                phase_limit = .12 if font_hint is not None else .16
                if score < phase_limit and second - score >= .006:
                    return text, value, min(.98, 1.0 - score * 1.7), face
        return None
    return text, value, min(.98, 1.0 - score * 1.7), font_hint


def _read_rotated_source_word(image, bbox, orientation):
    # Rotate grayscale source before binarizing: rotating a binary raster joins
    # neighbouring digits and loses punctuation on small slanted labels.
    box = (max(0, bbox[0] - 1), max(0, bbox[1] - 1),
           min(image.width, bbox[2] + 2), min(image.height, bbox[3] + 2))
    gray = image.crop(box).convert('L')
    return _cached_rotated_source_word(gray.width, gray.height, gray.tobytes(), orientation)


@lru_cache(maxsize=512)
def _cached_rotated_source_word(width, height, pixels, orientation):
    gray = Image.frombytes('L', (width, height), pixels)
    background = 255 if ImageStat.Stat(gray).mean[0] >= 128 else 0
    candidates, heights, readings, masks, rotations = {}, [], [], [], []
    observed = _normalized_gray_word(gray)
    if observed is None:
        return None
    for delta in ((0, -1, 1, -3, 3) if orientation % 90 else (0,)):
        rotated = gray.rotate(orientation + delta, expand=True, fillcolor=background,
                               resample=Image.Resampling.BICUBIC if (orientation + delta) % 90 else Image.Resampling.NEAREST)
        rotations.append(rotated)
        mask = _binary_mask(rotated)
        masks.append(mask)
        bounds = _bbox(mask)
        if bounds is None:
            continue
        heights.append(bounds[3] - bounds[1] + 1)
        native = _ocr_numeric(mask)
        if native is not None:
            candidates[native[0]] = (native[1], (1 - native[2]) * .6)
            if native[2] >= .76 and _word_template_score(mask, native[0]) < .29:
                readings.append((native, mask))
    if readings:
        native, mask = max(readings, key=lambda item: item[0][2])
        votes = {}
        for reading, _ in readings:
            votes[reading[1]] = votes.get(reading[1], 0) + 1
        majority = max(votes, key=votes.get)
        has_majority = len(votes) > 1 and votes[majority] >= math.ceil(len(readings) * .7)
        if has_majority:
            # Agreement between deskew variants of this SAME word is stronger
            # than a tiny confidence increase on a dissenting resampling.
            native, mask = next(item for item in readings if item[0][1] == majority)
        alternatives = {reading[0]: reading[1] for reading, _ in readings}
        if not has_majority and len(set(alternatives.values())) > 1:
            height = min(heights)
            # The estimated axis angle can be a degree off. Compare every
            # candidate over the same bounded angle window, rather than letting
            # one resampling's slightly higher glyph confidence choose a digit.
            deltas = (0, -1, 1, -3, 3) if orientation % 90 else (0,)
            ranked = sorted((min(_rotated_gray_score(observed, text, height, orientation + d)
                                 for d in deltas), text, value)
                            for text, value in alternatives.items())
            score, text, value = ranked[0]
            second = next((s for s, _, other in ranked[1:] if other != value), 1.0)
            if score < .12 and second - score >= .008:
                return text, value, min(.98, 1 - score * 2)
        independent = _read_independent_word(mask)
        if independent is not None and independent[1] != native[1]:
            height = min(heights)
            deltas = (0, -1, 1, -3, 3) if orientation % 90 else (0,)
            a = min(_rotated_gray_score(observed, independent[0], height, orientation + d) for d in deltas)
            b = min(_rotated_gray_score(observed, native[0], height, orientation + d) for d in deltas)
            if a < .12 and a + .01 < b:
                return independent
        return native
    # Only unread words pay for extra contrast. A darker threshold can separate
    # anti-aliased 000/16 bridges that survive every angle at the default level.
    recovered = []
    for rotated in rotations[:3]:
        for threshold in (160, 215):
            ink = rotated.point([int(v <= threshold) if background >= 128 else int(v >= 255 - threshold)
                                 for v in range(256)])
            data = ink.tobytes()
            mask = [bytearray(data[y * ink.width:(y + 1) * ink.width]) for y in range(ink.height)]
            masks.append(mask)
            native = _ocr_numeric(mask)
            if native is not None and native[2] >= .8 and _word_template_score(mask, native[0]) < .24:
                recovered.append(native)
    if recovered:
        for reading in recovered:
            candidates[reading[0]] = (reading[1], (1 - reading[2]) * .6)
    for mask in masks:
        for text, value, error in _independent_word_candidates(mask, cut_prior=True)[:4]:
            previous = candidates.get(text)
            candidates[text] = (value, min(error, previous[1]) if previous else error)
    if not candidates or not heights:
        return None
    height = min(heights)
    # Verify in the original grayscale orientation. Binary deskew can join
    # 000 into one component or turn a 6 into 0; don't trust its OCR confidence.
    shortlist = sorted(candidates.items(), key=lambda item: item[1][1])[:5]
    ranked = sorted((_rotated_gray_score(observed, text, height, orientation), text, value)
                    for text, (value, _) in shortlist)
    score, text, value = ranked[0]
    second = next((s for s, _, other in ranked[1:] if other != value), 1.0)
    if (recovered or score > .14 or second - score < .008) and orientation % 90:
        # Global deskew can be a few degrees off, or individual labels jitter.
        # Refine only this unread word and only its five best image hypotheses.
        refined = []
        for previous, text, value in ranked[:5]:
            error = min([previous] + [_rotated_gray_score(observed, text, height, orientation + delta)
                                      for delta in (-1, 1, -3, 3)])
            refined.append((error, text, value))
        ranked = sorted(refined)
        score, text, value = ranked[0]
        second = next((s for s, _, other in ranked[1:] if other != value), 1.0)
    minimum_margin = .006 if score < .04 else .008
    if score > .14 or second - score < minimum_margin:
        recovered = [r for m in masks if (r := _read_independent_word(m)) is not None and r[2] >= .7]
        return max(recovered, key=lambda r: r[2]) if recovered else None
    return text, value, min(.98, 1.0 - score * 2)


def _check_tick_cancelled(cancelled):
    if cancelled is not None and cancelled():
        raise CancelledError('Tick detection cancelled.')
