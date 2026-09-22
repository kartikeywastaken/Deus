use crate::correlation::features::{Direction, EvidenceFamily, EvidenceSignal, SignalType};
use crate::db::models::Classification;
use std::collections::{HashMap, HashSet};

pub fn get_signal_weight(signal_type: SignalType) -> f64 {
    match signal_type {
        SignalType::EmailExact => 45.0,
        SignalType::DirectProfileLink => 40.0,
        SignalType::SharedPersonalDomain => 30.0,
        SignalType::DomainExact => 30.0,
        SignalType::UrlExact => 25.0,
        SignalType::SharedIdentifier => 25.0,
        SignalType::UsernameExact => 20.0,
        SignalType::RepositoryRelationship => 20.0,
        SignalType::UsernameSimilarity => 12.0,
        SignalType::DisplayNameSimilarity => 10.0,
        SignalType::ProjectOverlap => 15.0,
        SignalType::OrganizationOverlap => 10.0,
        SignalType::BioSimilarity => 8.0,
        SignalType::TopicOverlap => 3.0,
        SignalType::LocationOverlap => 5.0,
        SignalType::ExactAvatar => 20.0,
        SignalType::ImageSimilarity => 16.0,
        SignalType::FaceSimilarity => 16.0,
        SignalType::DifferentFace => 40.0,
        SignalType::ExplicitIdentityConflict => 40.0,
        SignalType::PersonalDomainConflict => 20.0,
        SignalType::BiographicalContradiction => 15.0,
        SignalType::LocationConflict => 15.0,
        SignalType::OrganizationConflict => 15.0,
        SignalType::NameSearchMention => 4.0,
    }
}

pub fn calculate_contribution(signal: &EvidenceSignal) -> f64 {
    let weight = get_signal_weight(signal.signal_type);
    let sign = match signal.direction {
        Direction::Support => 1.0,
        Direction::Contradict => -1.0,
        Direction::Neutral => 0.0,
    };
    sign * weight * signal.normalized_score * signal.reliability
}

#[derive(Debug, Clone)]
pub struct ScoredPair {
    pub raw_score: f64,
    pub normalized_score: f64,
    pub classification: Classification,
    pub support_family_count: usize,
    pub contradiction_family_count: usize,
    pub selected_evidence: Vec<EvidenceSignal>,
}

pub fn score_evidence(signals: &[EvidenceSignal]) -> ScoredPair {
    // Group signals by EvidenceFamily and select strongest contribution
    let mut family_groups: HashMap<EvidenceFamily, Vec<&EvidenceSignal>> = HashMap::new();
    for sig in signals {
        if sig.direction != Direction::Neutral {
            family_groups.entry(sig.evidence_family).or_default().push(sig);
        }
    }

    let mut selected: Vec<EvidenceSignal> = Vec::new();
    for (_family, sigs) in family_groups {
        if let Some(&best) = sigs.iter().max_by(|a, b| {
            let contrib_a = calculate_contribution(a).abs();
            let contrib_b = calculate_contribution(b).abs();
            contrib_a.partial_cmp(&contrib_b).unwrap_or(std::cmp::Ordering::Equal)
        }) {
            selected.push(best.clone());
        }
    }

    let raw_score: f64 = selected.iter().map(calculate_contribution).sum();
    let normalized_score = (raw_score / 100.0).clamp(-1.0, 1.0);

    let support_families: HashSet<_> = selected
        .iter()
        .filter(|s| s.direction == Direction::Support)
        .map(|s| s.evidence_family)
        .collect();

    let contradiction_families: HashSet<_> = selected
        .iter()
        .filter(|s| s.direction == Direction::Contradict)
        .map(|s| s.evidence_family)
        .collect();

    let classification = classify(raw_score, &selected, support_families.len());

    ScoredPair {
        raw_score,
        normalized_score,
        classification,
        support_family_count: support_families.len(),
        contradiction_family_count: contradiction_families.len(),
        selected_evidence: selected,
    }
}

fn classify(raw_score: f64, selected: &[EvidenceSignal], support_family_count: usize) -> Classification {
    if raw_score <= -10.0 {
        return Classification::Contradictory;
    }

    let has_anchor = selected.iter().any(|s| {
        s.direction == Direction::Support
            && matches!(
                s.signal_type,
                SignalType::EmailExact
                    | SignalType::DirectProfileLink
                    | SignalType::SharedPersonalDomain
                    | SignalType::DomainExact
                    | SignalType::ExactAvatar
                    | SignalType::ProjectOverlap
            )
    });

    let has_direct_link = selected.iter().any(|s| {
        s.direction == Direction::Support
            && s.signal_type == SignalType::DirectProfileLink
            && calculate_contribution(s) >= 35.0
    });

    let material_contradiction = selected.iter().any(|s| {
        s.direction == Direction::Contradict && calculate_contribution(s).abs() >= 15.0
    });

    if raw_score >= 40.0 && support_family_count >= 2 && has_anchor && !material_contradiction {
        Classification::Strong
    } else if raw_score >= 20.0 && !material_contradiction && (support_family_count >= 2 || has_direct_link) {
        Classification::Likely
    } else if raw_score >= 7.0 {
        Classification::Ambiguous
    } else {
        Classification::Weak
    }
}
