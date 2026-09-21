use crate::image::metadata::{apply_exif_orientation, get_exif_orientation};
use crate::image::validation::{inspect_magic_bytes, VerifiedImageFormat};
use image::{imageops::FilterType, GenericImageView};
use sha2::{Digest, Sha256};
use std::io::Cursor;

#[derive(Clone, Debug)]
pub struct PreparedPhoto {
    pub original_width: u32,
    pub original_height: u32,
    pub prepared_width: u32,
    pub prepared_height: u32,
    pub prepared_f32: Vec<f32>,
    pub sha256: [u8; 32],
}

pub fn compute_grayscale_stats(luma_pixels: &[u8]) -> (f32, f32) {
    if luma_pixels.is_empty() {
        return (0.0, 0.0);
    }
    let n = luma_pixels.len() as f32;
    let sum: f32 = luma_pixels.iter().map(|&p| p as f32).sum();
    let mean = sum / n;
    let variance: f32 = luma_pixels
        .iter()
        .map(|&p| {
            let diff = p as f32 - mean;
            diff * diff
        })
        .sum::<f32>()
        / n;
    (mean, variance.sqrt())
}

pub fn prepare_photo(bytes: &[u8]) -> Result<PreparedPhoto, String> {
    const MAX_BYTES: usize = 5 * 1024 * 1024; // 5 MB
    if bytes.len() > MAX_BYTES {
        return Err(format!("Photo exceeds maximum allowed size of 5 MB (got {} bytes)", bytes.len()));
    }

    let format = inspect_magic_bytes(bytes).map_err(|_| {
        "Unsupported media type: photo must be JPEG, PNG, or WebP".to_string()
    })?;

    if !matches!(format, VerifiedImageFormat::Jpeg | VerifiedImageFormat::Png | VerifiedImageFormat::Webp) {
        return Err("Unsupported media type: photo must be JPEG, PNG, or WebP".to_string());
    }

    // Inspect dimensions before full image decode
    let reader = image::io::Reader::new(Cursor::new(bytes))
        .with_guessed_format()
        .map_err(|e| format!("Failed to read image header: {e}"))?;

    let (width, height) = reader
        .into_dimensions()
        .map_err(|e| format!("Failed to inspect image dimensions: {e}"))?;

    const MAX_PIXELS: u64 = 16_000_000; // 16 MP
    if (width as u64 * height as u64) > MAX_PIXELS {
        return Err(format!("Photo dimensions ({}x{}) exceed 16 MP limit", width, height));
    }

    // Decode image
    let raw_img = image::load_from_memory(bytes)
        .map_err(|e| format!("Failed to decode photo: {e}"))?;

    // Apply EXIF orientation BEFORE anything else
    let orientation = get_exif_orientation(bytes);
    let oriented_img = apply_exif_orientation(raw_img, orientation);

    let (orig_w, orig_h) = oriented_img.dimensions();
    let grayscale_img = oriented_img.to_luma8();

    // Check detail: grayscale std dev >= 12.0
    let (_mean, std_dev) = compute_grayscale_stats(grayscale_img.as_raw());
    if std_dev < 12.0 {
        return Err(format!("Photo has almost no detail / low variance (std dev {:.2} < 12.0)", std_dev));
    }

    // Downscale so longest side = 96 px using Lanczos3
    let max_side = orig_w.max(orig_h);
    let (prep_w, prep_h) = if max_side <= 96 {
        (orig_w.max(1), orig_h.max(1))
    } else if orig_w >= orig_h {
        let h = ((orig_h as u64 * 96) / orig_w as u64).max(1) as u32;
        (96, h)
    } else {
        let w = ((orig_w as u64 * 96) / orig_h as u64).max(1) as u32;
        (w, 96)
    };

    let resized = image::imageops::resize(
        &grayscale_img,
        prep_w,
        prep_h,
        FilterType::Lanczos3,
    );

    let prepared_f32: Vec<f32> = resized.as_raw().iter().map(|&p| p as f32).collect();

    // Compute SHA-256 of original upload bytes
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let sha256_result: [u8; 32] = hasher.finalize().into();

    Ok(PreparedPhoto {
        original_width: orig_w,
        original_height: orig_h,
        prepared_width: prep_w,
        prepared_height: prep_h,
        prepared_f32,
        sha256: sha256_result,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_compute_grayscale_stats() {
        let flat = vec![128u8; 100];
        let (mean, std) = compute_grayscale_stats(&flat);
        assert_eq!(mean, 128.0);
        assert_eq!(std, 0.0);

        let textured: Vec<u8> = (0..100).map(|i| (i * 2) as u8).collect();
        let (_mean, std) = compute_grayscale_stats(&textured);
        assert!(std > 20.0);
    }
}
