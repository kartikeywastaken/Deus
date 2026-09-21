pub mod avatars;
pub mod matcher;
pub mod prepare;
pub mod store;

#[cfg(test)]
mod tests;

pub use matcher::{match_avatar, MatchMethod, PhotoMatchResult, Verdict};
pub use prepare::{prepare_photo, PreparedPhoto};
pub use store::{get_photo_store, PhotoStore};
