use crate::photo_match::matcher::PhotoMatchResult;
use crate::photo_match::prepare::PreparedPhoto;
use std::collections::{HashMap, VecDeque};
use std::net::IpAddr;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};
use uuid::Uuid;

static PHOTO_STORE_INSTANCE: OnceLock<Arc<Mutex<PhotoStore>>> = OnceLock::new();

pub fn get_photo_store() -> Arc<Mutex<PhotoStore>> {
    PHOTO_STORE_INSTANCE
        .get_or_init(|| Arc::new(Mutex::new(PhotoStore::new())))
        .clone()
}

#[derive(Clone, Debug)]
pub struct StoreEntry {
    pub token: String,
    pub search_id: Uuid,
    pub prepared: PreparedPhoto,
    pub created_at: Instant,
    pub match_cache: HashMap<String, PhotoMatchResult>, // Keyed by avatar_url
}

pub struct PhotoStore {
    entries: HashMap<String, StoreEntry>, // Keyed by token
    lru_order: VecDeque<String>,          // Tokens ordered from oldest to newest
    search_to_token: HashMap<Uuid, String>,
    ip_limits: HashMap<IpAddr, Vec<Instant>>,
    ttl: Duration,
    max_capacity: usize,
}

impl Default for PhotoStore {
    fn default() -> Self {
        Self::new()
    }
}

impl PhotoStore {
    pub fn new() -> Self {
        Self {
            entries: HashMap::new(),
            lru_order: VecDeque::new(),
            search_to_token: HashMap::new(),
            ip_limits: HashMap::new(),
            ttl: Duration::from_secs(30 * 60), // 30 minutes
            max_capacity: 16,
        }
    }

    pub fn check_rate_limit(&mut self, ip: IpAddr) -> bool {
        let max_hourly: usize = std::env::var("PHOTO_MATCH_PER_IP_HOURLY")
            .ok()
            .and_then(|s| s.parse().ok())
            .unwrap_or(20);

        let now = Instant::now();
        let one_hour = Duration::from_secs(3600);

        let timestamps = self.ip_limits.entry(ip).or_default();
        timestamps.retain(|t| now.duration_since(*t) < one_hour);

        if timestamps.len() >= max_hourly {
            return false;
        }

        timestamps.push(now);
        true
    }

    pub fn cleanup_expired(&mut self) {
        let now = Instant::now();
        let ttl = self.ttl;

        let expired_tokens: Vec<String> = self
            .entries
            .iter()
            .filter(|(_, entry)| now.duration_since(entry.created_at) >= ttl)
            .map(|(t, _)| t.clone())
            .collect();

        for token in expired_tokens {
            self.remove_token(&token);
        }
    }

    fn remove_token(&mut self, token: &str) {
        if let Some(entry) = self.entries.remove(token) {
            self.search_to_token.remove(&entry.search_id);
        }
        self.lru_order.retain(|t| t != token);
    }

    pub fn insert(&mut self, search_id: Uuid, prepared: PreparedPhoto) -> String {
        self.cleanup_expired();

        // If search already has an uploaded photo, replace/remove old one
        if let Some(old_token) = self.search_to_token.remove(&search_id) {
            self.remove_token(&old_token);
        }

        // Evict LRU if at capacity
        while self.entries.len() >= self.max_capacity {
            if let Some(oldest_token) = self.lru_order.pop_front() {
                if let Some(entry) = self.entries.remove(&oldest_token) {
                    self.search_to_token.remove(&entry.search_id);
                }
            } else {
                break;
            }
        }

        let token = Uuid::new_v4().to_string();
        let entry = StoreEntry {
            token: token.clone(),
            search_id,
            prepared,
            created_at: Instant::now(),
            match_cache: HashMap::new(),
        };

        self.search_to_token.insert(search_id, token.clone());
        self.entries.insert(token.clone(), entry);
        self.lru_order.push_back(token.clone());

        token
    }

    pub fn get(&mut self, token: &str, search_id: Uuid) -> Option<StoreEntry> {
        self.cleanup_expired();
        let entry = self.entries.get(token)?;

        if entry.search_id != search_id {
            return None;
        }

        Some(entry.clone())
    }

    pub fn cache_result(&mut self, token: &str, avatar_url: String, result: PhotoMatchResult) {
        if let Some(entry) = self.entries.get_mut(token) {
            entry.match_cache.insert(avatar_url, result);
        }
    }

    pub fn get_cached_result(&self, token: &str, avatar_url: &str) -> Option<PhotoMatchResult> {
        self.entries
            .get(token)
            .and_then(|e| e.match_cache.get(avatar_url).cloned())
    }

    pub fn delete(&mut self, token: &str, search_id: Uuid) -> bool {
        self.cleanup_expired();
        if let Some(entry) = self.entries.get(token) {
            if entry.search_id == search_id {
                self.remove_token(token);
                return true;
            }
        }
        false
    }
}
