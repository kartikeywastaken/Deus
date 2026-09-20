// src/osint/email/holehe.rs
//
// Runs the separately-installed `holehe` CLI (GPL-3.0, github.com/megadose/holehe) as a
// subprocess and parses the CSV it writes. Deus does not reimplement any of holehe's
// per-site logic; it only calls the binary the operator installed themselves
// (`pipx install holehe`) and reads the result.
//
// The caller (mod.rs) must only call `check` when the request has self_audit_confirmed = true.

use crate::osint::email::types::{SiteResult, Status};
use serde::Deserialize;
use std::env;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::Duration;
use tokio::process::Command;
use tokio::time::timeout;
use tracing::warn;
use uuid::Uuid;

#[derive(Debug, Deserialize)]
struct HoleheRow {
    name: String,
    domain: String,
    #[serde(rename = "rateLimit")]
    rate_limit: String,
    exists: String,
    #[serde(rename = "emailrecovery")]
    email_recovery: String,
    #[serde(rename = "phoneNumber")]
    phone_number: String,
    others: String,
}

fn parse_bool(s: &str) -> Option<bool> {
    match s.trim() {
        "True" => Some(true),
        "False" => Some(false),
        _ => None,
    }
}

fn is_none_like(s: &str) -> bool {
    let t = s.trim();
    t.is_empty() || t == "None"
}

fn human_label(domain: &str) -> String {
    let base = domain
        .trim_end_matches(".com")
        .trim_end_matches(".org")
        .trim_end_matches(".io")
        .trim_end_matches(".net");
    base.replace(['.', '_', '-'], " ")
        .split_whitespace()
        .map(|w| {
            let mut c = w.chars();
            match c.next() {
                Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn cant_check(reason: impl Into<String>) -> SiteResult {
    SiteResult {
        id: "holehe".to_string(),
        label: "Multi-site account check".to_string(),
        status: Status::CantCheck,
        via: "holehe".to_string(),
        reason: Some(reason.into()),
        username: None,
        profile_url: None,
        detail: None,
    }
}

/// Row to return instead of running holehe when the request lacks self_audit_confirmed.
pub fn consent_required() -> SiteResult {
    cant_check("confirmation required (tick \"This is my own email\")")
}

/// Runs holehe for `email` and returns one SiteResult per site it checked.
/// On any failure (binary missing, timeout, no output) returns a single CantCheck row,
/// never a NotRegistered.
pub async fn check(email: &str) -> Vec<SiteResult> {
    // Defence in depth: the email is passed as a single argv element (no shell), but refuse
    // anything that could be parsed as a flag or contains whitespace/control characters.
    if email.starts_with('-') || email.chars().any(|c| c.is_whitespace() || c.is_control()) {
        return vec![cant_check("invalid email for holehe")];
    }

    let binary = env::var("HOLEHE_BINARY").unwrap_or_else(|_| "holehe".to_string());
    let password_recovery = env::var("HOLEHE_PASSWORD_RECOVERY")
        .map(|v| v.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    // NOTE: never pass holehe's `-T`. It has no type=int, so `-T 10` reaches httpx as the string
    // "10" and every request raises TypeError, which holehe reports as "rate limited" for all sites.
    let total_timeout: u64 = env::var("HOLEHE_TOTAL_TIMEOUT_SECONDS")
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(90);

    // holehe self-updates on start when PyPI has a newer version: it runs
    // `pip3 install --upgrade holehe`, prints "Holehe has just been updated" and exits
    // WITHOUT scanning. Retry once in that case.
    for attempt in 0..2 {
        match run_once(&binary, email, password_recovery, total_timeout).await {
            RunOutcome::Rows(rows) => return rows,
            RunOutcome::SelfUpdated if attempt == 0 => continue,
            RunOutcome::SelfUpdated => {
                return vec![cant_check(
                    "holehe keeps self-updating instead of scanning; upgrade it manually (pipx upgrade holehe)",
                )]
            }
            RunOutcome::Failed(reason) => return vec![cant_check(reason)],
        }
    }
    vec![cant_check("holehe did not run")]
}

enum RunOutcome {
    Rows(Vec<SiteResult>),
    SelfUpdated,
    Failed(String),
}

async fn run_once(
    binary: &str,
    email: &str,
    password_recovery: bool,
    total_timeout: u64,
) -> RunOutcome {
    // holehe writes its CSV into the current working directory, so give each run its own.
    let work_dir = env::temp_dir().join(format!("deus-holehe-{}", Uuid::new_v4()));
    if let Err(e) = tokio::fs::create_dir_all(&work_dir).await {
        return RunOutcome::Failed(format!("could not create scratch dir: {e}"));
    }

    let mut cmd = Command::new(binary);
    cmd.current_dir(&work_dir)
        .arg(email)
        .arg("-C")
        .arg("--no-color")
        .arg("--no-clear");
    if !password_recovery {
        cmd.arg("--no-password-recovery");
    }
    cmd.kill_on_drop(true)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let output = match timeout(Duration::from_secs(total_timeout), cmd.output()).await {
        Ok(Ok(o)) => o,
        Ok(Err(e)) if e.kind() == std::io::ErrorKind::NotFound => {
            cleanup(&work_dir).await;
            return RunOutcome::Failed("holehe is not installed (try: pipx install holehe)".into());
        }
        Ok(Err(e)) => {
            cleanup(&work_dir).await;
            return RunOutcome::Failed(format!("failed to launch holehe: {e}"));
        }
        Err(_) => {
            cleanup(&work_dir).await;
            return RunOutcome::Failed("holehe timed out".into());
        }
    };

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    let csv_path = find_csv(&work_dir).await;
    let content = match &csv_path {
        Some(p) => tokio::fs::read_to_string(p).await.unwrap_or_default(),
        None => String::new(),
    };
    cleanup(&work_dir).await;

    if csv_path.is_none() {
        if stdout.contains("just been updated") {
            return RunOutcome::SelfUpdated;
        }
        if !output.status.success() {
            warn!("holehe exited with {}: {}", output.status, stderr.trim());
        }
        let hint: String = stderr.trim().chars().rev().take(200).collect::<Vec<_>>().into_iter().rev().collect();
        return RunOutcome::Failed(if hint.is_empty() {
            "holehe produced no output".to_string()
        } else {
            format!("holehe produced no output ({hint})")
        });
    }

    RunOutcome::Rows(parse_csv(&content))
}

async fn cleanup(dir: &Path) {
    let _ = tokio::fs::remove_dir_all(dir).await;
}

async fn find_csv(dir: &Path) -> Option<PathBuf> {
    let mut entries = tokio::fs::read_dir(dir).await.ok()?;
    while let Ok(Some(entry)) = entries.next_entry().await {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) == Some("csv") {
            return Some(path);
        }
    }
    None
}

pub(crate) fn parse_csv(content: &str) -> Vec<SiteResult> {
    if content.trim().is_empty() {
        return vec![cant_check("holehe CSV was empty")];
    }

    let mut reader = csv::ReaderBuilder::new()
        .has_headers(true)
        .flexible(true)
        .from_reader(content.as_bytes());
    let mut results = Vec::new();

    for record in reader.deserialize::<HoleheRow>() {
        let row = match record {
            Ok(r) => r,
            Err(e) => {
                warn!("skipping unparsable holehe CSV row: {e}");
                continue;
            }
        };

        let rate_limited = parse_bool(&row.rate_limit).unwrap_or(false);
        let exists = parse_bool(&row.exists);

        let (status, reason) = match (rate_limited, exists) {
            (true, _) => (Status::CantCheck, Some("site error or rate limit".to_string())),
            (false, Some(true)) => (Status::Registered, None),
            (false, Some(false)) => (Status::NotRegistered, None),
            (false, None) => (Status::CantCheck, Some("no verdict returned".to_string())),
        };

        // Recovery hints are partially masked by the sites; surface only that one exists,
        // not the masked values themselves.
        let mut detail_parts = Vec::new();
        if !is_none_like(&row.email_recovery) {
            detail_parts.push("recovery email on file");
        }
        if !is_none_like(&row.phone_number) {
            detail_parts.push("recovery phone on file");
        }
        let _ = &row.others; // intentionally not surfaced

        results.push(SiteResult {
            id: format!("holehe:{}", row.name),
            label: human_label(&row.domain),
            status,
            via: "holehe".to_string(),
            reason,
            username: None,
            profile_url: None,
            detail: if detail_parts.is_empty() {
                None
            } else {
                Some(detail_parts.join(" · "))
            },
        });
    }

    if results.is_empty() {
        return vec![cant_check("holehe CSV had no usable rows")];
    }
    results
}

#[cfg(test)]
mod tests {
    use super::*;

    const SAMPLE: &str = "name,domain,method,frequent_rate_limit,rateLimit,exists,emailrecovery,phoneNumber,others\n\
github,github.com,register,False,False,True,None,None,None\n\
spotify,spotify.com,login,False,False,False,None,None,None\n\
adobe,adobe.com,password recovery,False,True,False,None,None,None\n\
twitter,twitter.com,register,False,False,True,ex****e@gmail.com,None,\"{'FullName': 'A, B'}\"\n";

    #[test]
    fn maps_registered_not_registered_rate_limited() {
        let rows = parse_csv(SAMPLE);
        assert_eq!(rows.len(), 4);
        assert_eq!(rows[0].status, Status::Registered);
        assert_eq!(rows[0].label, "Github");
        assert_eq!(rows[1].status, Status::NotRegistered);
        assert_eq!(rows[2].status, Status::CantCheck);
        assert_eq!(rows[2].reason.as_deref(), Some("site error or rate limit"));
    }

    #[test]
    fn rate_limited_is_never_not_registered() {
        let rows = parse_csv(SAMPLE);
        assert!(rows.iter().filter(|r| r.id == "holehe:adobe").all(|r| r.status != Status::NotRegistered));
    }

    #[test]
    fn masked_recovery_values_are_not_exposed() {
        let rows = parse_csv(SAMPLE);
        let tw = rows.iter().find(|r| r.id == "holehe:twitter").unwrap();
        assert_eq!(tw.status, Status::Registered);
        assert_eq!(tw.detail.as_deref(), Some("recovery email on file"));
        assert!(!tw.detail.as_deref().unwrap().contains("ex****"));
    }

    #[test]
    fn empty_and_garbage_input_is_cant_check() {
        for input in ["", "   ", "not,a,holehe,csv\n1,2,3,4"] {
            let rows = parse_csv(input);
            assert_eq!(rows.len(), 1);
            assert_eq!(rows[0].status, Status::CantCheck);
        }
    }

    #[tokio::test]
    async fn missing_binary_is_cant_check() {
        std::env::set_var("HOLEHE_BINARY", "definitely-not-a-real-binary-xyz");
        let rows = check("someone@example.com").await;
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].status, Status::CantCheck);
        assert!(rows[0].reason.as_deref().unwrap().contains("not installed"));
    }

    #[tokio::test]
    async fn flag_like_email_is_rejected() {
        let rows = check("--help").await;
        assert_eq!(rows[0].status, Status::CantCheck);
    }
}