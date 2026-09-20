use crate::db::models::Classification;
use petgraph::algo::tarjan_scc;
use petgraph::graph::{NodeIndex, UnGraph};
use std::collections::HashMap;
use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct HypothesisCluster {
    pub rank: i32,
    pub overall_score: f64,
    pub classification: Classification,
    pub profile_ids: Vec<Uuid>,
}

pub fn build_hypotheses(
    profiles: &[Uuid],
    pairwise_scores: &[(Uuid, Uuid, f64, Classification)],
) -> Vec<HypothesisCluster> {
    if profiles.is_empty() {
        return vec![];
    }

    let mut graph = UnGraph::<Uuid, f64>::new_undirected();
    let mut node_map: HashMap<Uuid, NodeIndex> = HashMap::new();

    for &pid in profiles {
        let node = graph.add_node(pid);
        node_map.insert(pid, node);
    }

    for &(left, right, score, classif) in pairwise_scores {
        if matches!(classif, Classification::Strong | Classification::Likely) {
            if let (Some(&n1), Some(&n2)) = (node_map.get(&left), node_map.get(&right)) {
                graph.add_edge(n1, n2, score);
            }
        }
    }

    let sccs = tarjan_scc(&graph);
    let mut clusters = Vec::new();

    for (idx, component) in sccs.into_iter().enumerate() {
        let member_ids: Vec<Uuid> = component.iter().map(|&n| graph[n]).collect();

        // Calculate average internal connection score
        let mut total_score = 0.0;
        let mut edge_count = 0;
        for &(l, r, score, _) in pairwise_scores {
            if member_ids.contains(&l) && member_ids.contains(&r) {
                total_score += score;
                edge_count += 1;
            }
        }

        let avg_score = if edge_count > 0 {
            total_score / edge_count as f64
        } else {
            10.0
        };

        let classification = if avg_score >= 40.0 {
            Classification::Strong
        } else if avg_score >= 20.0 {
            Classification::Likely
        } else {
            Classification::Ambiguous
        };

        clusters.push(HypothesisCluster {
            rank: (idx + 1) as i32,
            overall_score: avg_score,
            classification,
            profile_ids: member_ids,
        });
    }

    clusters.sort_by(|a, b| b.overall_score.partial_cmp(&a.overall_score).unwrap());
    for (i, c) in clusters.iter_mut().enumerate() {
        c.rank = (i + 1) as i32;
    }

    clusters
}
