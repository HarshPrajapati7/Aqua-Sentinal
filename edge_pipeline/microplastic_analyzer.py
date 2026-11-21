import math
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional

import cv2
import numpy as np


MORPHOLOGY_COLORS = {
    "fiber": (255, 165, 0),
    "bead": (0, 220, 120),
    "film": (220, 120, 255),
    "fragment": (255, 100, 80),
}


def classify_morphology(
    aspect_ratio: float, circularity: float, solidity: float
) -> str:
    if aspect_ratio >= 3.0 and circularity < 0.45:
        return "fiber"
    if circularity >= 0.78 and aspect_ratio <= 1.35 and solidity >= 0.90:
        return "bead"
    if solidity < 0.72 and circularity < 0.60:
        return "film"
    return "fragment"


def compute_size_histogram(diameters_um: List[float]) -> Dict[str, int]:
    bins = {
        "1-10 um": 0,
        "10-25 um": 0,
        "25-50 um": 0,
        "50-100 um": 0,
        ">100 um": 0,
    }
    for diameter in diameters_um:
        if diameter < 10.0:
            bins["1-10 um"] += 1
        elif diameter < 25.0:
            bins["10-25 um"] += 1
        elif diameter < 50.0:
            bins["25-50 um"] += 1
        elif diameter <= 100.0:
            bins["50-100 um"] += 1
        else:
            bins[">100 um"] += 1
    return bins


def analyze_membrane_image(
    image_bgr: np.ndarray,
    volume_ml: float,
    px_per_um: float = 0.8,
    min_um: float = 1.0,
    max_um: float = 150.0,
    dark_particles_on_bright_bg: bool = True,
    output_annotated_path: Optional[Path] = None,
) -> Dict[str, Any]:
    if image_bgr is None or image_bgr.size == 0:
        raise ValueError("Empty input image for microplastic analysis.")

    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    bg = cv2.GaussianBlur(gray, (51, 51), 0)
    normalized = cv2.divide(gray, np.maximum(bg, 1), scale=255)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(normalized)
    blurred = cv2.GaussianBlur(enhanced, (3, 3), 0)

    thresh_mode = (
        cv2.THRESH_BINARY_INV
        if dark_particles_on_bright_bg
        else cv2.THRESH_BINARY
    )
    binary = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        thresh_mode,
        31,
        7,
    )
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    contours, _ = cv2.findContours(
        cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    annotated = image_bgr.copy()
    particles: List[Dict[str, Any]] = []
    min_area_px = math.pi * ((min_um * px_per_um) / 2.0) ** 2
    max_area_px = math.pi * ((max_um * px_per_um) / 2.0) ** 2

    for idx, contour in enumerate(contours, start=1):
        area_px = cv2.contourArea(contour)
        if area_px < max(4.0, min_area_px) or area_px > max_area_px:
            continue

        perimeter_px = cv2.arcLength(contour, True)
        if perimeter_px <= 0:
            continue

        equiv_diam_px = 2.0 * math.sqrt(area_px / math.pi)
        equiv_diam_um = equiv_diam_px / px_per_um
        _, (width, height), _ = cv2.minAreaRect(contour)
        major_px = max(width, height, 1.0)
        minor_px = max(min(width, height), 1.0)
        aspect_ratio = major_px / minor_px
        circularity = min(
            1.0, (4.0 * math.pi * area_px) / (perimeter_px**2)
        )
        hull_area = cv2.contourArea(cv2.convexHull(contour))
        solidity = area_px / hull_area if hull_area > 0 else 1.0
        morphology = classify_morphology(
            aspect_ratio, circularity, solidity
        )

        particle_index = len(particles) + 1
        particles.append(
            {
                "idx": particle_index,
                "equiv_diameter_um": round(equiv_diam_um, 2),
                "major_axis_um": round(major_px / px_per_um, 2),
                "minor_axis_um": round(minor_px / px_per_um, 2),
                "aspect_ratio": round(aspect_ratio, 2),
                "circularity": round(circularity, 3),
                "solidity": round(solidity, 3),
                "morphology": morphology,
            }
        )

        color = MORPHOLOGY_COLORS.get(morphology, (255, 255, 255))
        cv2.drawContours(annotated, [contour], -1, color, 2)
        x, y, _, _ = cv2.boundingRect(contour)
        cv2.putText(
            annotated,
            f"#{particle_index} {morphology[0].upper()} {equiv_diam_um:.0f}um",
            (x, max(12, y - 4)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.38,
            color,
            1,
            cv2.LINE_AA,
        )

    total_count = len(particles)
    volume_l = max(volume_ml / 1000.0, 1e-6)
    particles_per_liter = round(total_count / volume_l, 2)
    diameters = [p["equiv_diameter_um"] for p in particles]
    mean_size_um = (
        round(float(np.mean(diameters)), 2) if diameters else 0.0
    )
    morphology_counts = Counter(p["morphology"] for p in particles)
    dominant_morphology = (
        morphology_counts.most_common(1)[0][0]
        if morphology_counts
        else "none"
    )
    loading_ratio = float(np.count_nonzero(cleaned)) / float(cleaned.size)

    if output_annotated_path is not None:
        output_annotated_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(output_annotated_path), annotated)

    return {
        "total_count": total_count,
        "particles_per_liter": particles_per_liter,
        "mean_size_um": mean_size_um,
        "dominant_morphology": dominant_morphology,
        "morphology_breakdown": dict(morphology_counts),
        "size_histogram": compute_size_histogram(diameters),
        "filter_loading_ratio": round(loading_ratio, 4),
        "particles": particles,
    }
