use crate::db::models::{QuestionType, SensitivityLevel};
use serde_json::json;
use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct QuestionCandidate {
    pub question_type: QuestionType,
    pub question_text: String,
    pub options: serde_json::Value,
    pub reason: String,
    pub affected_profile_ids: Vec<Uuid>,
    pub expected_information_gain: f64,
    pub sensitivity_level: SensitivityLevel,
}

pub fn select_best_question(
    ambiguous_profiles: &[Uuid],
    highest_hypothesis_score: f64,
) -> Option<QuestionCandidate> {
    if ambiguous_profiles.len() < 2 || highest_hypothesis_score >= 35.0 {
        return None;
    }

    Some(QuestionCandidate {
        question_type: QuestionType::YesNo,
        question_text: "Do these candidate profiles belong to the same person?".to_string(),
        options: json!([
            {"label": "Yes, same person", "value": "same"},
            {"label": "No, different people", "value": "different"},
            {"label": "Unsure", "value": "unsure"}
        ]),
        reason: "Highest ranked hypothesis is ambiguous; confirming relationship prunes candidate space.".to_string(),
        affected_profile_ids: ambiguous_profiles.to_vec(),
        expected_information_gain: 0.85,
        sensitivity_level: SensitivityLevel::Low,
    })
}
