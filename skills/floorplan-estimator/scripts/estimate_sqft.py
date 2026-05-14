#!/usr/bin/env python3
"""
Pixel-polygon square footage estimator for NYC co-op floor plans.

Usage:
    python estimate_sqft.py <image_path> \
        --room-px-width <W> --room-px-height <H> \
        --room-ft-width <W> --room-ft-height <H> \
        [--listing-price <price>]

The script:
1. Thresholds the image to non-white pixels
2. Morphologically closes to bridge thin wall gaps
3. Finds the largest connected blob (the apartment polygon)
4. Fills interior, counts pixels = gross area in pixels
5. Calibrates px-to-ft scale from the labeled calibration room
6. Computes sqft = polygon_pixels / (px_per_ft)^2
7. Validates $/sqft if price is provided

Outputs JSON to stdout with: sqft, px_per_ft, polygon_pixels,
calibration_room_sqft, price_per_sqft (if price given), sanity_check.
"""

import argparse
import json
import sys
import numpy as np
from PIL import Image

def load_and_threshold(image_path, threshold=220):
    """Load image, convert to grayscale, threshold to non-white."""
    img = Image.open(image_path).convert('L')
    arr = np.array(img)
    # Non-white = apartment content (walls, rooms, labels)
    binary = (arr < threshold).astype(np.uint8)
    return binary, arr.shape

def morphological_close(binary, iterations=5):
    """Close small gaps in walls using dilation then erosion."""
    from scipy import ndimage
    struct = ndimage.generate_binary_structure(2, 2)  # 8-connected
    dilated = ndimage.binary_dilation(binary, structure=struct, iterations=iterations)
    closed = ndimage.binary_erosion(dilated, structure=struct, iterations=iterations)
    return closed.astype(np.uint8)

def largest_blob(binary):
    """Find the largest connected component and fill its interior."""
    from scipy import ndimage
    labeled, num_features = ndimage.label(binary)
    if num_features == 0:
        print("ERROR: No blobs detected in image", file=sys.stderr)
        sys.exit(1)

    # Find largest component by pixel count
    sizes = ndimage.sum(binary, labeled, range(1, num_features + 1))
    largest_label = np.argmax(sizes) + 1

    # Extract and fill
    blob = (labeled == largest_label).astype(np.uint8)
    filled = ndimage.binary_fill_holes(blob).astype(np.uint8)

    return filled, int(np.sum(filled))

def compute_sqft(polygon_pixels, room_px_w, room_px_h, room_ft_w, room_ft_h):
    """Compute sqft from polygon pixels and calibration room dimensions."""
    # Scale from calibration room
    px_per_ft_x = room_px_w / room_ft_w
    px_per_ft_y = room_px_h / room_ft_h

    # Average the two scales (ideally they're close)
    px_per_ft = (px_per_ft_x + px_per_ft_y) / 2
    scale_divergence = abs(px_per_ft_x - px_per_ft_y) / px_per_ft * 100

    # Compute area
    sqft = polygon_pixels / (px_per_ft ** 2)
    calibration_room_sqft = room_ft_w * room_ft_h

    return {
        'sqft': round(sqft),
        'px_per_ft': round(px_per_ft, 2),
        'px_per_ft_x': round(px_per_ft_x, 2),
        'px_per_ft_y': round(px_per_ft_y, 2),
        'scale_divergence_pct': round(scale_divergence, 1),
        'polygon_pixels': polygon_pixels,
        'calibration_room_sqft': round(calibration_room_sqft, 1),
    }

def sanity_check(sqft, price=None):
    """Check if $/sqft is in the expected Manhattan range ($900-$1800)."""
    result = {'in_range': True, 'warning': None}
    if price and sqft > 0:
        ppsf = price / sqft
        result['price_per_sqft'] = round(ppsf)
        if ppsf < 900:
            result['in_range'] = False
            result['warning'] = f'$/sqft ${ppsf:.0f} is BELOW $900 floor — sqft likely overestimated'
        elif ppsf > 1800:
            result['in_range'] = False
            result['warning'] = f'$/sqft ${ppsf:.0f} is ABOVE $1800 ceiling — sqft likely underestimated'
    return result

def main():
    parser = argparse.ArgumentParser(description='Estimate apartment sqft from floor plan')
    parser.add_argument('image_path', help='Path to floor plan image')
    parser.add_argument('--room-px-width', type=float, required=True,
                        help='Calibration room width in pixels')
    parser.add_argument('--room-px-height', type=float, required=True,
                        help='Calibration room height in pixels')
    parser.add_argument('--room-ft-width', type=float, required=True,
                        help='Calibration room width in feet')
    parser.add_argument('--room-ft-height', type=float, required=True,
                        help='Calibration room height in feet')
    parser.add_argument('--listing-price', type=float, default=None,
                        help='Listing price for $/sqft sanity check')
    parser.add_argument('--threshold', type=int, default=220,
                        help='Grayscale threshold for non-white (default 220)')
    parser.add_argument('--close-iterations', type=int, default=5,
                        help='Morphological closing iterations (default 5)')
    args = parser.parse_args()

    # Step 1-3: Load, threshold, close, largest blob
    binary, shape = load_and_threshold(args.image_path, args.threshold)
    closed = morphological_close(binary, args.close_iterations)
    filled, polygon_pixels = largest_blob(closed)

    # Step 4: Compute sqft
    result = compute_sqft(
        polygon_pixels,
        args.room_px_width, args.room_px_height,
        args.room_ft_width, args.room_ft_height
    )

    # Step 5: Sanity check
    check = sanity_check(result['sqft'], args.listing_price)
    result['sanity_check'] = check
    result['image_shape'] = list(shape)

    print(json.dumps(result, indent=2))

    if check.get('warning'):
        print(f"\nWARNING: {check['warning']}", file=sys.stderr)
        sys.exit(2)  # Non-zero but not 1, so caller knows it's a sanity warning not crash

if __name__ == '__main__':
    main()
