use std::collections::HashSet;

pub const RESERVED_PATHS: &[&str] = &[
    "about", "account", "accounts", "api", "blog", "c", "channel", "company", "contact",
    "direct", "explore", "features", "feed", "groups", "help", "home", "i", "in", "intent",
    "login", "messages", "notifications", "orgs", "p", "podcasts", "posts", "pricing",
    "privacy", "r", "reel", "reels", "search", "settings", "share", "signup", "status",
    "stories", "tags", "terms", "topics", "trending", "u", "user", "users", "videos", "watch",
];

pub fn extract_handle(raw_input: &str) -> Option<(String, String)> {
    let input = percent_decode(raw_input.trim());
    if input.is_empty() {
        return None;
    }

    if !input.contains('/') && !input.contains('.') && !input.contains(':') {
        let clean = clean_handle(&input);
        if clean.is_empty() || is_reserved(&clean) {
            return None;
        }
        return Some(("username".to_string(), clean));
    }

    let full_url = if !input.starts_with("http://") && !input.starts_with("https://") {
        format!("https://{}", input)
    } else {
        input.clone()
    };

    let parsed = url::Url::parse(&full_url).ok()?;
    let raw_host = parsed.host_str()?.to_lowercase();

    let host = raw_host
        .trim_start_matches("www.")
        .trim_start_matches("m.")
        .trim_start_matches("mobile.");

    let path = parsed.path().trim_matches('/');
    let segments: Vec<&str> = if path.is_empty() {
        Vec::new()
    } else {
        path.split('/').map(clean_handle_ref).collect()
    };

    let reserved: HashSet<&str> = RESERVED_PATHS.iter().copied().collect();

    // 1. GitHub
    if let Some(res) = extract_single_segment_host(host, &segments, &reserved, "github.com", "github") {
        return Some(res);
    }

    // 2. Twitter / X
    if (host == "x.com" || host == "twitter.com" || host.ends_with(".twitter.com") || host.ends_with(".x.com"))
        && !segments.is_empty()
        && !segments[0].is_empty()
        && !reserved.contains(segments[0].to_lowercase().as_str())
    {
        return Some(("twitter".to_string(), segments[0].to_string()));
    }

    // 3. Instagram
    if let Some(res) = extract_single_segment_host(host, &segments, &reserved, "instagram.com", "instagram") {
        return Some(res);
    }

    // 4. TikTok: tiktok.com/@{u}
    if host == "tiktok.com" || host.ends_with(".tiktok.com") {
        for seg in &segments {
            if let Some(h) = seg.strip_prefix('@') {
                let clean = clean_handle_ref(h);
                if !clean.is_empty() && !reserved.contains(clean.to_lowercase().as_str()) {
                    return Some(("tiktok".to_string(), clean.to_string()));
                }
            }
        }
    }

    // 5. YouTube: youtube.com/@{u}|/c/{u}|/user/{u}
    if host == "youtube.com" || host.ends_with(".youtube.com") || host == "youtu.be" {
        if !segments.is_empty() {
            if (segments[0] == "c" || segments[0] == "user") && segments.len() > 1 {
                let clean = segments[1];
                if !clean.is_empty() && !reserved.contains(clean.to_lowercase().as_str()) {
                    return Some(("youtube".to_string(), clean.to_string()));
                }
            } else if !segments[0].is_empty() && !reserved.contains(segments[0].to_lowercase().as_str()) {
                return Some(("youtube".to_string(), segments[0].to_string()));
            }
        }
        return None;
    }

    // 6. Reddit: reddit.com/user/{u} or reddit.com/u/{u}
    if (host == "reddit.com" || host.ends_with(".reddit.com")) && segments.len() >= 2 && (segments[0] == "user" || segments[0] == "u") {
        let clean = segments[1];
        if !clean.is_empty() {
            return Some(("reddit".to_string(), clean.to_string()));
        }
        return None;
    }

    // 7. LinkedIn: linkedin.com/in/{u}
    if (host == "linkedin.com" || host.ends_with(".linkedin.com")) && segments.len() >= 2 && segments[0] == "in" {
        let clean = segments[1];
        if !clean.is_empty() {
            return Some(("linkedin".to_string(), clean.to_string()));
        }
        return None;
    }

    // 8. Medium: medium.com/@{u} and {u}.medium.com
    if host == "medium.com" || host.ends_with(".medium.com") {
        if let Some(subdomain) = raw_host.strip_suffix(".medium.com") {
            let clean = clean_handle_ref(subdomain.trim_start_matches("www.").trim_start_matches("m."));
            if !clean.is_empty() && clean != "www" && clean != "m" {
                return Some(("medium".to_string(), clean.to_string()));
            }
        }
        if !segments.is_empty() {
            if let Some(h) = segments[0].strip_prefix('@') {
                let clean = clean_handle_ref(h);
                if !clean.is_empty() {
                    return Some(("medium".to_string(), clean.to_string()));
                }
            }
        }
    }

    // 9. Dev.to
    if let Some(res) = extract_single_segment_host(host, &segments, &reserved, "dev.to", "devto") {
        return Some(res);
    }

    // 10. GitLab
    if let Some(res) = extract_single_segment_host(host, &segments, &reserved, "gitlab.com", "gitlab") {
        return Some(res);
    }

    // 11. Twitch
    if let Some(res) = extract_single_segment_host(host, &segments, &reserved, "twitch.tv", "twitch") {
        return Some(res);
    }

    // 12. Telegram: t.me/{u} or telegram.me/{u}
    if (host == "t.me" || host == "telegram.me" || host.ends_with(".t.me") || host.ends_with(".telegram.me"))
        && !segments.is_empty() && !segments[0].is_empty() && !reserved.contains(segments[0].to_lowercase().as_str()) {
        return Some(("telegram".to_string(), segments[0].to_string()));
    }

    // 13. Keybase
    if let Some(res) = extract_single_segment_host(host, &segments, &reserved, "keybase.io", "keybase") {
        return Some(res);
    }

    // 14. Pinterest
    if let Some(res) = extract_single_segment_host(host, &segments, &reserved, "pinterest.com", "pinterest") {
        return Some(res);
    }

    // 15. CodePen
    if let Some(res) = extract_single_segment_host(host, &segments, &reserved, "codepen.io", "codepen") {
        return Some(res);
    }

    // 16. SoundCloud
    if let Some(res) = extract_single_segment_host(host, &segments, &reserved, "soundcloud.com", "soundcloud") {
        return Some(res);
    }

    // 17. Tumblr: {u}.tumblr.com
    if host == "tumblr.com" || host.ends_with(".tumblr.com") {
        if let Some(subdomain) = raw_host.strip_suffix(".tumblr.com") {
            let clean = clean_handle_ref(subdomain.trim_start_matches("www.").trim_start_matches("m."));
            if !clean.is_empty() && clean != "www" && clean != "m" {
                return Some(("tumblr".to_string(), clean.to_string()));
            }
        }
        if !segments.is_empty() && !segments[0].is_empty() && !reserved.contains(segments[0].to_lowercase().as_str()) {
            return Some(("tumblr".to_string(), segments[0].to_string()));
        }
    }

    // 18. StackOverflow: stackoverflow.com/users/{id}/{name}
    if (host == "stackoverflow.com" || host.ends_with(".stackoverflow.com")) && segments.len() >= 3 && segments[0] == "users" {
        let name = segments[2];
        if !name.is_empty() {
            return Some(("stackoverflow".to_string(), name.to_string()));
        }
    }

    if !segments.is_empty() && !segments[0].is_empty() {
        let h = segments[0];
        if !reserved.contains(h.to_lowercase().as_str()) && !h.starts_with("profile.php") {
            let platform = host.split('.').next().unwrap_or("website").to_string();
            return Some((platform, h.to_string()));
        }
    }

    None
}

fn extract_single_segment_host(
    host: &str,
    segments: &[&str],
    reserved: &HashSet<&str>,
    domain: &str,
    platform: &str,
) -> Option<(String, String)> {
    if (host == domain || host.ends_with(&format!(".{}", domain)))
        && !segments.is_empty()
        && !segments[0].is_empty()
    {
        let h = segments[0];
        if !reserved.contains(h.to_lowercase().as_str()) {
            return Some((platform.to_string(), h.to_string()));
        }
    }
    None
}

fn is_reserved(h: &str) -> bool {
    RESERVED_PATHS.contains(&h.to_lowercase().as_str())
}

fn percent_decode(s: &str) -> String {
    let mut bytes = Vec::new();
    let s_bytes = s.as_bytes();
    let mut i = 0;
    while i < s_bytes.len() {
        if s_bytes[i] == b'%' && i + 2 < s_bytes.len() {
            if let Ok(h) = u8::from_str_radix(std::str::from_utf8(&s_bytes[i + 1..i + 3]).unwrap_or(""), 16) {
                bytes.push(h);
                i += 3;
                continue;
            }
        }
        bytes.push(s_bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&bytes).to_string()
}

fn clean_handle(s: &str) -> String {
    clean_handle_ref(s).to_string()
}

fn clean_handle_ref(s: &str) -> &str {
    let s = s.trim();
    let s = s.split('?').next().unwrap_or(s);
    let s = s.split('#').next().unwrap_or(s);
    let s = s.trim_matches('/');
    if let Some(stripped) = s.strip_prefix('@') {
        stripped
    } else {
        s
    }
}

pub fn normalize_canonical_url(url_str: &str) -> String {
    let trimmed = url_str.trim();
    if trimmed.is_empty() {
        return String::new();
    }

    let url_with_scheme = if !trimmed.starts_with("http://") && !trimmed.starts_with("https://") {
        format!("https://{}", trimmed)
    } else {
        trimmed.to_string()
    };

    if let Ok(mut parsed) = url::Url::parse(&url_with_scheme) {
        if parsed.scheme() == "http" {
            let _ = parsed.set_scheme("https");
        }

        if parsed.query().is_some() {
            let tracking_keys = [
                "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                "fbclid", "gclid", "ref", "ref_src", "s", "t", "igshid", "mkt_tok", "source"
            ];
            let pairs: Vec<(String, String)> = parsed
                .query_pairs()
                .filter(|(k, _)| {
                    let k_lower = k.to_lowercase();
                    !tracking_keys.contains(&k_lower.as_str()) && !k_lower.starts_with("utm_")
                })
                .map(|(k, v)| (k.into_owned(), v.into_owned()))
                .collect();

            if pairs.is_empty() {
                parsed.set_query(None);
            } else {
                let mut serializer = parsed.query_pairs_mut();
                serializer.clear();
                for (k, v) in pairs {
                    serializer.append_pair(&k, &v);
                }
            }
        }

        parsed.set_fragment(None);

        let mut res = parsed.to_string();
        let path = parsed.path().to_string();
        if res.ends_with('/') && path != "/" {
            res.pop();
        }
        res
    } else {
        let mut s = trimmed.to_string();
        if s.ends_with('/') && s.len() > 1 {
            s.pop();
        }
        s
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_handle_all_patterns() {
        assert_eq!(extract_handle("https://github.com/octocat"), Some(("github".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("github.com/octocat"), Some(("github".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://github.com/octocat/my-repo"), Some(("github".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://www.tiktok.com/@octocat"), Some(("tiktok".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("www.tiktok.com/@octocat"), Some(("tiktok".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://tiktok.com/%40octocat"), Some(("tiktok".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://medium.com/@octocat"), Some(("medium".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://octocat.medium.com"), Some(("medium".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://youtube.com/@octocat"), Some(("youtube".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://youtube.com/c/octocat"), Some(("youtube".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://youtube.com/user/octocat"), Some(("youtube".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://linkedin.com/in/octocat/"), Some(("linkedin".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://x.com/octocat/status/123?s=20"), Some(("twitter".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://twitter.com/octocat"), Some(("twitter".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://reddit.com/user/octocat"), Some(("reddit".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://reddit.com/u/octocat"), Some(("reddit".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://dev.to/octocat"), Some(("devto".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://gitlab.com/octocat"), Some(("gitlab".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://twitch.tv/octocat"), Some(("twitch".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://t.me/octocat"), Some(("telegram".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://keybase.io/octocat"), Some(("keybase".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://pinterest.com/octocat"), Some(("pinterest".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://codepen.io/octocat"), Some(("codepen".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://soundcloud.com/octocat"), Some(("soundcloud".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://octocat.tumblr.com"), Some(("tumblr".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("https://stackoverflow.com/users/12345/octocat"), Some(("stackoverflow".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("@octocat"), Some(("username".to_string(), "octocat".to_string())));
        assert_eq!(extract_handle("octocat"), Some(("username".to_string(), "octocat".to_string())));
    }

    #[test]
    fn test_extract_handle_unsupported_and_reserved() {
        assert_eq!(extract_handle("https://facebook.com/profile.php?id=1000123"), None);
        assert_eq!(extract_handle("https://youtube.com/channel/UC123456"), None);
        assert_eq!(extract_handle("https://github.com/orgs"), None);
        assert_eq!(extract_handle("https://github.com/settings"), None);
        assert_eq!(extract_handle("https://x.com/privacy"), None);
        assert_eq!(extract_handle("https://"), None);
        assert_eq!(extract_handle("   "), None);
    }
}
