use exif::{Reader, Tag, Value};
use image::DynamicImage;
use std::io::Cursor;

/// Extracts the EXIF orientation integer (1..=8) if present in the image bytes.
pub fn get_exif_orientation(bytes: &[u8]) -> Option<u32> {
    let mut cursor = Cursor::new(bytes);
    let exif = Reader::new().read_from_container(&mut cursor).ok()?;
    for field in exif.fields() {
        if field.tag == Tag::Orientation {
            if let Value::Short(ref v) = field.value {
                return v.first().map(|&o| o as u32);
            }
        }
    }
    None
}

/// Applies EXIF orientation transformation to a DynamicImage.
pub fn apply_exif_orientation(img: DynamicImage, orientation: Option<u32>) -> DynamicImage {
    match orientation {
        Some(2) => img.fliph(),
        Some(3) => img.rotate180(),
        Some(4) => img.flipv(),
        Some(5) => img.rotate90().fliph(),
        Some(6) => img.rotate90(),
        Some(7) => img.rotate270().fliph(),
        Some(8) => img.rotate270(),
        _ => img, // 1 or None or invalid
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::GenericImageView;

    #[test]
    fn test_apply_exif_orientation_identity() {
        let img = DynamicImage::new_rgb8(10, 20);
        let oriented = apply_exif_orientation(img.clone(), Some(1));
        assert_eq!(oriented.width(), 10);
        assert_eq!(oriented.height(), 20);

        let rotated = apply_exif_orientation(img, Some(6));
        assert_eq!(rotated.width(), 20);
        assert_eq!(rotated.height(), 10);
    }
}
