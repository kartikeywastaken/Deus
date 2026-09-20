use image::GenericImageView;
use img_hash::{HashAlg, HasherConfig};
use sha2::{Digest, Sha256};

#[derive(Debug, Clone)]
pub struct ImageFingerprint {
    pub sha256: String,
    pub phash: String,
    pub width: u32,
    pub height: u32,
}

pub fn compute_image_fingerprint(image_bytes: &[u8]) -> Result<ImageFingerprint, String> {
    let mut hasher = Sha256::new();
    hasher.update(image_bytes);
    let sha256_hex = hex::encode(hasher.finalize());

    let img = image::load_from_memory(image_bytes).map_err(|e| e.to_string())?;
    let (width, height) = (img.width(), img.height());

    let phash_builder = HasherConfig::new().hash_alg(HashAlg::Gradient).to_hasher();
    let phash = phash_builder.hash_image(&img);
    let phash_str = phash.to_base64();

    Ok(ImageFingerprint {
        sha256: sha256_hex,
        phash: phash_str,
        width,
        height,
    })
}
