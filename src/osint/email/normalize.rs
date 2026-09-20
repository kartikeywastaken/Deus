use regex::Regex;

#[derive(Debug, Clone)]
pub struct NormalizedEmail {
    pub raw: String,
    pub normalized: String,
    pub base_email: String,
    pub local_part: String,
    pub domain: String,
}

pub fn normalize_email(input: &str) -> Result<NormalizedEmail, String> {
    let trimmed = input.trim().to_lowercase();
    if trimmed.is_empty() {
        return Err("Email address cannot be empty".to_string());
    }

    if trimmed.starts_with('-') {
        return Err("Email address cannot start with '-'".to_string());
    }

    if trimmed.len() > 254 {
        return Err("Email address exceeds maximum length of 254 characters".to_string());
    }

    let last_at = trimmed.rfind('@').ok_or_else(|| "Invalid email format: missing '@'".to_string())?;
    let local_part = &trimmed[..last_at];
    let domain = &trimmed[last_at + 1..];

    if local_part.is_empty() {
        return Err("Invalid email format: empty local part".to_string());
    }

    if local_part.len() > 64 {
        return Err("Email local-part exceeds maximum length of 64 characters".to_string());
    }

    if domain.is_empty() || !domain.contains('.') {
        return Err("Invalid email format: invalid domain name".to_string());
    }

    let email_regex = Regex::new(
        r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
    ).unwrap();

    if !email_regex.is_match(&trimmed) {
        return Err("Invalid email format".to_string());
    }

    // Strip +tag if present
    let local_without_tag = if let Some(plus_idx) = local_part.find('+') {
        &local_part[..plus_idx]
    } else {
        local_part
    };

    // Handle gmail / googlemail dot-insensitivity
    let is_gmail = domain == "gmail.com" || domain == "googlemail.com";
    let base_local = if is_gmail {
        local_without_tag.replace('.', "")
    } else {
        local_without_tag.to_string()
    };

    let base_email = format!("{}@{}", base_local, domain);
    let normalized = format!("{}@{}", local_part, domain);

    Ok(NormalizedEmail {
        raw: input.to_string(),
        normalized,
        base_email,
        local_part: base_local,
        domain: domain.to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_email_normalization_valid() {
        let res = normalize_email("  Shivangi.Sharma+test@Gmail.com ").unwrap();
        assert_eq!(res.normalized, "shivangi.sharma+test@gmail.com");
        assert_eq!(res.base_email, "shivangisharma@gmail.com");
        assert_eq!(res.local_part, "shivangisharma");
        assert_eq!(res.domain, "gmail.com");
    }

    #[test]
    fn test_email_normalization_invalid() {
        assert!(normalize_email("invalid-email").is_err());
        assert!(normalize_email("-user@domain.com").is_err());
        assert!(normalize_email("@domain.com").is_err());
        assert!(normalize_email("user@").is_err());
    }
}
