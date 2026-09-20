use axum::{
    extract::Path,
    response::sse::{Event, Sse},
};
use futures::stream::{self, Stream};
use std::convert::Infallible;
use std::time::Duration;
use tokio_stream::StreamExt;
use uuid::Uuid;

pub async fn sse_events(
    Path(id): Path<Uuid>,
) -> Sse<impl Stream<Item = Result<Event, Infallible>>> {
    let stream = stream::repeat_with(move || {
        Event::default()
            .event("update")
            .data(format!(r#"{{"search_run_id": "{}"}}"#, id))
    })
    .map(Ok)
    .throttle(Duration::from_secs(1));

    Sse::new(stream)
}
