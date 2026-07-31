"""
Image preprocessing and encoding utilities for ParchaAI prescription extraction.

This module provides functions to:
- Load prescription images using OpenCV
- Validate image quality and format
- Encode images to base64 for API transmission
- Handle various image formats (JPG, PNG, etc.)
"""

import base64
import logging
from pathlib import Path
from typing import Optional, Tuple, Union
import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class ImageProcessingError(Exception):
    """Custom exception for image processing errors."""
    pass


def load_image(image_path: Union[str, Path]) -> np.ndarray:
    """
    Load an image from disk using OpenCV.
    
    Parameters
    ----------
    image_path : str or Path
        Path to the image file
    
    Returns
    -------
    np.ndarray
        Loaded image in BGR format (OpenCV default)
    
    Raises
    ------
    ImageProcessingError
        If image cannot be loaded or is invalid
    """
    image_path = Path(image_path)
    
    if not image_path.exists():
        raise ImageProcessingError(f"Image file not found: {image_path}")
    
    if not image_path.is_file():
        raise ImageProcessingError(f"Path is not a file: {image_path}")
    
    # Load image
    logger.debug(f"Loading image: {image_path}")
    image = cv2.imread(str(image_path))
    
    if image is None:
        raise ImageProcessingError(
            f"Failed to load image: {image_path}. "
            f"File may be corrupted or in an unsupported format."
        )
    
    logger.info(f"Loaded image: {image_path.name} (shape: {image.shape})")
    return image


def validate_image(image: np.ndarray, min_size: Tuple[int, int] = (100, 100)) -> bool:

    if image is None:
        raise ImageProcessingError("Image is None")
    
    if len(image.shape) < 2:
        raise ImageProcessingError(f"Invalid image shape: {image.shape}")
    
    height, width = image.shape[:2]
    min_width, min_height = min_size
    
    if width < min_width or height < min_height:
        raise ImageProcessingError(
            f"Image too small: {width}x{height}. "
            f"Minimum required: {min_width}x{min_height}"
        )
    
    logger.debug(f"Image validation passed: {width}x{height}")
    return True


def encode_image_to_base64(
    image_input: Union[str, Path, np.ndarray],
    validate: bool = True
) -> str:
    
    if isinstance(image_input, np.ndarray):
        image = image_input
        if validate:
            validate_image(image)

        try:
            success, encoded = cv2.imencode('.png', image)
            if not success:
                raise ImageProcessingError("Failed to encode numpy image")
            image_bytes = encoded.tobytes()
        except Exception as e:
            raise ImageProcessingError(f"Failed to encode numpy image: {e}")
    else:
        image_path = Path(image_input)

        # Validate if requested
        if validate:
            image = load_image(image_path)
            validate_image(image)

        # Read raw file bytes
        try:
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
        except Exception as e:
            raise ImageProcessingError(f"Failed to read image file: {e}")

    # Encode to base64
    try:
        b64_string = base64.b64encode(image_bytes).decode('utf-8')
    except Exception as e:
        raise ImageProcessingError(f"Failed to encode image to base64: {e}")

    logger.debug(f"Encoded image to base64: {len(b64_string)} characters")
    return b64_string


def create_data_url(
    image_input: Union[str, Path, np.ndarray],
    validate: bool = True
) -> str:

    if isinstance(image_input, np.ndarray):
        mime_type = 'png'
        filename = 'processed_image'
        b64_string = encode_image_to_base64(image_input, validate)
    else:
        image_path = Path(image_input)

        # Determine MIME type from extension
        extension = image_path.suffix.lower().lstrip('.')
        mime_type_map = {
            'jpg': 'jpeg',
            'jpeg': 'jpeg',
            'png': 'png',
            'gif': 'gif',
            'bmp': 'bmp',
            'webp': 'webp'
        }

        mime_type = mime_type_map.get(extension, extension)
        filename = image_path.name

        # Encode image
        b64_string = encode_image_to_base64(image_path, validate)

    # Create data URL
    data_url = f"data:image/{mime_type};base64,{b64_string}"

    logger.debug(f"Created data URL for {filename} (MIME: image/{mime_type})")
    return data_url


def get_image_info(image_path: Union[str, Path]) -> dict:
    """
    Get detailed information about an image file.
    
    Parameters
    ----------
    image_path : str or Path
        Path to the image file
    
    Returns
    -------
    dict
        Dictionary containing image information:
        - path: str
        - filename: str
        - format: str
        - width: int
        - height: int
        - channels: int
        - size_bytes: int
        - size_mb: float

    """
    image_path = Path(image_path)
    
    # Load image
    image = load_image(image_path)
    
    # Get file size
    size_bytes = image_path.stat().st_size
    size_mb = size_bytes / (1024 * 1024)
    
    # Extract dimensions
    height, width = image.shape[:2]
    channels = image.shape[2] if len(image.shape) > 2 else 1
    
    return {
        'path': str(image_path),
        'filename': image_path.name,
        'format': image_path.suffix.upper().lstrip('.'),
        'width': width,
        'height': height,
        'channels': channels,
        'size_bytes': size_bytes,
        'size_mb': round(size_mb, 2)
    }


def preprocess_for_ocr(
    image: np.ndarray,
    resize_width: Optional[int] = None,
    enhance_contrast: bool = False
) -> np.ndarray:

    processed = image.copy()
    
    # Resize if requested
    if resize_width is not None:
        height, width = processed.shape[:2]
        aspect_ratio = height / width
        new_height = int(resize_width * aspect_ratio)
        processed = cv2.resize(processed, (resize_width, new_height))
        logger.debug(f"Resized image to {resize_width}x{new_height}")
    
    # Enhance contrast if requested
    if enhance_contrast:
        # Convert to LAB color space
        lab = cv2.cvtColor(processed, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        
        # Apply CLAHE to L channel
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        l = clahe.apply(l)
        
        # Merge back
        processed = cv2.merge([l, a, b])
        processed = cv2.cvtColor(processed, cv2.COLOR_LAB2BGR)
        logger.debug("Applied contrast enhancement")
    
    return processed


def upscale_for_vlm(image_path: Union[str, Path], min_long_edge: int = 1200) -> np.ndarray:
    """Upscale small images and sharpen them before VLM processing, preserving color."""
    image = load_image(image_path)
    height, width = image.shape[:2]
    long_edge = max(height, width)

    # Mild color sharpening to help segment faint hand-written strokes
    if long_edge >= min_long_edge:
        blur = cv2.GaussianBlur(image, (0, 0), 1.0)
        sharpened = cv2.addWeighted(image, 1.3, blur, -0.3, 0)
        return sharpened

    scale = min_long_edge / float(long_edge)
    new_width = max(1, int(round(width * scale)))
    new_height = max(1, int(round(height * scale)))
    resized = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_CUBIC)

    blur = cv2.GaussianBlur(resized, (0, 0), 1.2)
    sharpened = cv2.addWeighted(resized, 1.4, blur, -0.4, 0)

    logger.info(f"Upscaled image to {new_width}x{new_height} and sharpened (color preserved)")
    return sharpened


def batch_load_images(image_paths: list[Union[str, Path]]) -> dict[str, np.ndarray]:

    images = {}
    
    for path in image_paths:
        try:
            image = load_image(path)
            images[Path(path).name] = image
        except ImageProcessingError as e:
            logger.error(f"Failed to load {path}: {e}")
            continue
    
    logger.info(f"Batch loaded {len(images)}/{len(image_paths)} images")
    return images


def save_image(image: np.ndarray, output_path: Union[str, Path]) -> None:

    output_path = Path(output_path)
    
    # Create parent directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save image
    success = cv2.imwrite(str(output_path), image)
    
    if not success:
        raise ImageProcessingError(f"Failed to save image: {output_path}")
    
    logger.info(f"Saved image: {output_path}")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def quick_encode(image_path: Union[str, Path]) -> str:

    return create_data_url(image_path, validate=True)


def is_valid_image_file(file_path: Union[str, Path]) -> bool:

    try:
        file_path = Path(file_path)
        
        if not file_path.exists() or not file_path.is_file():
            return False
        
        # Check extension
        valid_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
        if file_path.suffix.lower() not in valid_extensions:
            return False
        
        # Try to load with PIL 
        with Image.open(file_path) as img:
            img.verify()
        
        return True
    
    except Exception:
        return False
