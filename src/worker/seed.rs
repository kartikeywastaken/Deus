use std::collections::HashSet;

pub const RESERVED_PATHS: &[&str] = &[
    "about", "api", "blog", "contact", "explore", "features", "feed", "help",
    "home", "login", "notifications", "orgs", "pricing", "privacy", "search",
    "settings", "signup", "terms", "topics", "trending", "user", "users",
];

pub fn extract_handle(raw_url: &str) -> Option<(String, String)> {
    let url_str = raw_url.trim();
    if url_str.is_empty() {
        return None;
    }

    if !url_str.contains("://") && !url_str.contains('.') {
        let clean = clean_handle(url_str);
        if clean.is_empty() || is_reserved(&clean) {
            return None;
        }
        return Some(("username".to_string(), clean));
    }

    let parsed = url::Url::parse(url_str).ok()?;
    let host = parsed.host_str()?.to_lowercase();
    let path = parsed.path().trim_matches('/');

    let reserved: HashSet<&str> = RESERVED_PATHS.iter().copied().collect();

    if host.contains("github.com") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("github".to_string(), h));
            }
        }
    }

    if host.contains("x.com") || host.contains("twitter.com") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("twitter".to_string(), h));
            }
        }
    }

    if host.contains("instagram.com") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("instagram".to_string(), h));
            }
        }
    }

    if host.contains("tiktok.com") {
        let segments: Vec<&str> = path.split('/').collect();
        for seg in segments {
            if let Some(h) = seg.strip_prefix('@') {
                let clean = clean_handle(h);
                if !clean.is_empty() && !reserved.contains(clean.to_lowercase().as_str()) {
                    return Some(("tiktok".to_string(), clean));
                }
            }
        }
    }

    if host.contains("youtube.com") || host.contains("youtu.be") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() {
            if let Some(h) = segments[0].strip_prefix('@') {
                let clean = clean_handle(h);
                if !clean.is_empty() { return Some(("youtube".to_string(), clean)); }
            }
            if (segments[0] == "c" || segments[0] == "user") && segments.len() > 1 {
                let clean = clean_handle(segments[1]);
                if !clean.is_empty() { return Some(("youtube".to_string(), clean)); }
            }
        }
    }

    if host.contains("reddit.com") {
        let segments: Vec<&str> = path.split('/').collect();
        if segments.len() >= 2 && (segments[0] == "user" || segments[0] == "u") {
            let clean = clean_handle(segments[1]);
            if !clean.is_empty() { return Some(("reddit".to_string(), clean)); }
        }
    }

    if host.contains("linkedin.com") {
        let segments: Vec<&str> = path.split('/').collect();
        if segments.len() >= 2 && segments[0] == "in" {
            let clean = clean_handle(segments[1]);
            if !clean.is_empty() { return Some(("linkedin".to_string(), clean)); }
        }
    }

    if host.contains("medium.com") {
        if let Some(subdomain) = host.strip_suffix(".medium.com") {
            let clean = clean_handle(subdomain);
            if !clean.is_empty() && clean != "www" {
                return Some(("medium".to_string(), clean));
            }
        }
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() {
            if let Some(h) = segments[0].strip_prefix('@') {
                let clean = clean_handle(h);
                if !clean.is_empty() { return Some(("medium".to_string(), clean)); }
            }
        }
    }

    if host.contains("dev.to") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("devto".to_string(), h));
            }
        }
    }

    if host.contains("gitlab.com") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("gitlab".to_string(), h));
            }
        }
    }

    if host.contains("twitch.tv") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("twitch".to_string(), h));
            }
        }
    }

    if host.contains("t.me") || host.contains("telegram.me") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("telegram".to_string(), h));
            }
        }
    }

    if host.contains("keybase.io") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("keybase".to_string(), h));
            }
        }
    }

    if host.contains("pinterest.com") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("pinterest".to_string(), h));
            }
        }
    }

    if host.contains("codepen.io") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("codepen".to_string(), h));
            }
        }
    }

    if host.contains("soundcloud.com") {
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("soundcloud".to_string(), h));
            }
        }
    }

    if host.contains("tumblr.com") {
        if let Some(subdomain) = host.strip_suffix(".tumblr.com") {
            let clean = clean_handle(subdomain);
            if !clean.is_empty() && clean != "www" {
                return Some(("tumblr".to_string(), clean));
            }
        }
        let segments: Vec<&str> = path.split('/').collect();
        if !segments.is_empty() && !segments[0].is_empty() {
            let h = clean_handle(segments[0]);
            if !reserved.contains(h.to_lowercase().as_str()) {
                return Some(("tumblr".to_string(), h));
            }
        }
    }

    if host.contains("stackoverflow.com") {
        let segments: Vec<&str> = path.split('/').collect();
        if segments.len() >= 3 && segments[0] == "users" {
            let name = clean_handle(segments[2]);
            if !name.is_empty() {
                return Some(("stackoverflow".to_string(), name));
            }
        }
    }

    let segments: Vec<&str> = path.split('/').collect();
    if !segments.is_empty() && !segments[0].is_empty() {
        let h = clean_handle(segments[0]);
        if !reserved.contains(h.to_lowercase().as_str()) {
            let platform = host.split('.').next().unwrap_or("website").to_string();
            return Some((platform, h));
        }
    }

    None
}

fn is_reserved(h: &str) -> bool {
    RESERVED_PATHS.contains(&h.to_lowercase().as_str())
}

fn clean_handle(s: &str) -> String {
    let s = s.trim();
    let s = s.split('?').next().unwrap_or(s);
    let s = s.split('#').next().unwrap_or(s);
    let s = s.trim_matches('/');
    s.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_handle_patterns() {
        assert_eq!(extract_handle("https://github.com/octocat"), Some(("github".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://github.com/octocat?tab=repositories"), Some(("github".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://x.com/elonmusk"), Some(("twitter".to_string(), "elonmusk".to_string())));
        assert_eq!(extract_handle("https://twitter.com/jack"), Some(("twitter".to_string(), "jack".to_string())));
        assert_eq!(extract_handle("https://instagram.com/zuck"), Some(("instagram".to_string(), "zuck".to_string())));
        assert_eq!(extract_handle("https://tiktok.com/@khaby.lame"), Some(("tiktok".to_string(), "khaby.lame".to_string())));
        assert_eq!(extract_handle("https://youtube.com/@mkbhd"), Some(("youtube".to_string(), "mkbhd".to_string())));
        assert_eq!(extract_handle("https://youtube.com/c/LinusTechTips"), Some(("youtube".to_string(), "LinusTechTips".to_string())));
        assert_eq!(extract_handle("https://youtube.com/user/google"), Some(("youtube".to_string(), "google".to_string())));
        assert_eq!(extract_handle("https://reddit.com/user/spez"), Some(("reddit".to_string(), "spez".to_string())));
        assert_eq!(extract_handle("https://reddit.com/u/spez"), Some(("reddit".to_string(), "spez".to_string())));
        assert_eq!(extract_handle("https://linkedin.com/in/satyanadella"), Some(("linkedin".to_string(), "satyanadella".to_string())));
        assert_eq!(extract_handle("https://medium.com/@ev"), Some(("medium".to_string(), "ev".to_string())));
        assert_eq!(extract_handle("https://alex.medium.com"), Some(("medium".to_string(), "alex".to_string())));
        assert_eq!(extract_handle("https://dev.to/ben"), Some(("devto".to_string(), "ben".to_string())));
        assert_eq!(extract_handle("https://gitlab.com/torvalds"), Some(("gitlab".to_string(), "torvalds".to_string())));
        assert_eq!(extract_handle("https://twitch.tv/shroud"), Some(("twitch".to_string(), "shroud".to_string())));
        assert_eq!(extract_handle("https://t.me/durov"), Some(("telegram".to_string(), "durov".to_string())));
        assert_eq!(extract_handle("https://keybase.io/max"), Some(("keybase".to_string(), "max".to_string())));
        assert_eq!(extract_handle("https://pinterest.com/design"), Some(("pinterest".to_string(), "design".to_string())));
        assert_eq!(extract_handle("https://codepen.io/chriscoyier"), Some(("codepen".to_string(), "chriscoyier".to_string())));
        assert_eq!(extract_handle("https://soundcloud.com/skrillex"), Some(("soundcloud".to_string(), "skrillex".to_string())));
        assert_eq!(extract_handle("https://staff.tumblr.com"), Some(("tumblr".to_string(), "staff".to_string())));
        assert_eq!(extract_handle("https://stackoverflow.com/users/22656/jon-skeet"), Some(("stackoverflow".to_string(), "jon-skeet".to_string())));
    }

    #[test]
    fn test_extract_handle_reserved_and_junk() {
        assert_eq!(extract_handle("https://github.com/orgs"), None);
        assert_eq!(extract_handle("https://github.com/explore"), None);
        assert_eq!(extract_handle("https://github.com/settings"), None);
        assert_eq!(extract_handle("https://x.com/privacy"), None);
        assert_eq!(extract_handle("https://"), None);
        assert_eq!(extract_handle("   "), None);
    }
}
