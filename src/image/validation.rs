use image::GenericImageView;
use std::env;

#[derive(Debug, thiserror::Error)]
pub enum ImageValidationError {
    #[error("Image exceeds maximum allowed size of {max_bytes} bytes")]
    PayloadTooLarge { max_bytes: u64 },
    #[error("Unsupported media type: image file signature or format unrecognized")]
    UnsupportedMediaType,
    #[error("Image appears corrupted or unreadable: {0}")]
    CorruptedImage(String),
    #[error("Image dimensions exceed safety limits (max 16384x16384 or 100MP)")]
    PathologicalDimensions,
}

pub fn get_max_upload_size() -> u64 {
    env::var("MAX_IMAGE_UPLOAD_SIZE_BYTES")
        .ok()
        .and_then(|s| s.parse::<u64>().ok())
        .unwrap_or(10 * 1024 * 1024) // Default 10 MB
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VerifiedImageFormat {
    Jpeg,
    Png,
    Gif,
    Webp,
    Bmp,
    Tiff,
}

impl VerifiedImageFormat {
    pub fn as_str(&self) -> &'static str {
        match self {
            VerifiedImageFormat::Jpeg => "JPEG",
            VerifiedImageFormat::Png => "PNG",
            VerifiedImageFormat::Gif => "GIF",
            VerifiedImageFormat::Webp => "WEBP",
            VerifiedImageFormat::Bmp => "BMP",
            VerifiedImageFormat::Tiff => "TIFF",
        }
    }
}

/// Inspect actual file signature (magic bytes) to verify format.
/// Never trust the client-provided MIME header.
pub fn inspect_magic_bytes(bytes: &[u8]) -> Result<VerifiedImageFormat, ImageValidationError> {
    if bytes.len() < 4 {
        return Err(ImageValidationError::UnsupportedMediaType);
    }

    // JPEG: FF D8 FF
    if bytes.starts_with(&[0xFF, 0xD8, 0xFF]) {
        return Ok(VerifiedImageFormat::Jpeg);
    }

    // PNG: 89 50 4E 47 0D 0A 1A 0A
    if bytes.starts_with(&[0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]) {
        return Ok(VerifiedImageFormat::Png);
    }

    // GIF: GIF87a or GIF89a
    if bytes.starts_with(b"GIF87a") || bytes.starts_with(b"GIF89a") {
        return Ok(VerifiedImageFormat::Gif);
    }

    // WEBP: RIFF....WEBP
    if bytes.len() >= 12 && bytes.starts_with(b"RIFF") && &bytes[8..12] == b"WEBP" {
        return Ok(VerifiedImageFormat::Webp);
    }

    // BMP: BM
    if bytes.starts_with(b"BM") {
        return Ok(VerifiedImageFormat::Bmp);
    }

    // TIFF: II*. or MM.*
    if bytes.starts_with(&[0x49, 0x49, 0x2A, 0x00]) || bytes.starts_with(&[0x4D, 0x4D, 0x00, 0x2A]) {
        return Ok(VerifiedImageFormat::Tiff);
    }

    Err(ImageValidationError::UnsupportedMediaType)
}

pub fn validate_image_payload(bytes: &[u8]) -> Result<(VerifiedImageFormat, u32, u32), ImageValidationError> {
    let max_size = get_max_upload_size();
    if bytes.len() as u64 > max_size {
        return Err(ImageValidationError::PayloadTooLarge { max_bytes: max_size });
    }

    let format = inspect_magic_bytes(bytes)?;

    // Decompression bomb & dimension safety validation
    let img = image::load_from_memory(bytes)
        .map_err(|e| ImageValidationError::CorruptedImage(e.to_string()))?;

    let width = img.width();
    let height = img.height();

    const MAX_DIM: u32 = 16_384;
    const MAX_PIXELS: u64 = 100_000_000;

    if width > MAX_DIM || height > MAX_DIM || (width as u64 * height as u64) > MAX_PIXELS {
        return Err(ImageValidationError::PathologicalDimensions);
    }

    Ok((format, width, height))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_magic_bytes_detection() {
        let jpeg = vec![0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10];
        assert_eq!(inspect_magic_bytes(&jpeg).unwrap(), VerifiedImageFormat::Jpeg);

        let png = vec![0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A];
        assert_eq!(inspect_magic_bytes(&png).unwrap(), VerifiedImageFormat::Png);

        let invalid = vec![0x00, 0x01, 0x02, 0x03];
        assert!(inspect_magic_bytes(&invalid).is_err());
    }
}
