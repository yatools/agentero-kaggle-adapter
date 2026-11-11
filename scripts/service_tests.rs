
#[cfg(test)]
mod kaggle_tests {
    use super::*;
    use crate::core::decision::SystemOneCredentials;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;
    use std::time::Duration;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    struct MockApi {
        endpoint: String,
        calls: Arc<AtomicUsize>,
        active: Arc<AtomicUsize>,
        peak: Arc<AtomicUsize>,
        bodies: Arc<Mutex<Vec<Value>>>,
        task: tokio::task::JoinHandle<()>,
    }

    impl Drop for MockApi {
        fn drop(&mut self) { self.task.abort(); }
    }

    struct Active(Arc<AtomicUsize>);
    impl Drop for Active {
        fn drop(&mut self) { self.0.fetch_sub(1, Ordering::SeqCst); }
    }

    impl MockApi {
        async fn start(delay: Duration, mode: &'static str) -> Self {
            let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
            let endpoint = format!("http://{}/v1/systemone", listener.local_addr().unwrap());
            let calls = Arc::new(AtomicUsize::new(0));
            let active = Arc::new(AtomicUsize::new(0));
            let peak = Arc::new(AtomicUsize::new(0));
            let bodies = Arc::new(Mutex::new(Vec::new()));
            let (c, a, p, b) = (calls.clone(), active.clone(), peak.clone(), bodies.clone());
            let task = tokio::spawn(async move {
                while let Ok((mut socket, _)) = listener.accept().await {
                    let (c, a, p, b) = (c.clone(), a.clone(), p.clone(), b.clone());
                    tokio::spawn(async move {
                        let mut raw = Vec::new();
                        let body = loop {
                            let mut buf = [0; 8192];
                            let n = socket.read(&mut buf).await.unwrap_or(0);
                            if n == 0 { return; }
                            raw.extend_from_slice(&buf[..n]);
                            if let Some(header_end) = raw.windows(4).position(|x| x == b"\r\n\r\n") {
                                let headers = String::from_utf8_lossy(&raw[..header_end]).to_lowercase();
                                let len: usize = headers.lines().find_map(|line| line.strip_prefix("content-length:")).unwrap().trim().parse().unwrap();
                                if raw.len() >= header_end + 4 + len {
                                    break serde_json::from_slice::<Value>(&raw[header_end+4..header_end+4+len]).unwrap();
                                }
                            }
                        };
                        b.lock().unwrap().push(body.clone());
                        c.fetch_add(1, Ordering::SeqCst);
                        let current = a.fetch_add(1, Ordering::SeqCst) + 1;
                        p.fetch_max(current, Ordering::SeqCst);
                        let _guard = Active(a);
                        let mut closed = [0; 1];
                        tokio::select! {
                            _ = tokio::time::sleep(delay) => {},
                            _ = socket.read(&mut closed) => { return; }
                        }
                        let mut answers = serde_json::Map::new();
                        if mode != "missing" {
                            for id in body["questions"].as_object().unwrap().keys() {
                                answers.insert(id.clone(), serde_json::json!({"score": 3.0}));
                            }
                        }
                        let response = serde_json::json!({"answers":answers}).to_string();
                        let status = if mode == "error" { "400 Bad Request" } else { "200 OK" };
                        let bytes = format!("HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}", response.len(), response);
                        let _ = socket.write_all(bytes.as_bytes()).await;
                    });
                }
            });
            Self {endpoint, calls, active, peak, bodies, task}
        }

        fn provider(&self) -> Arc<SystemOneProvider> {
            let endpoint = self.endpoint.clone();
            Arc::new(SystemOneProvider::new(reqwest::Client::builder().no_proxy().timeout(Duration::from_secs(5)).build().unwrap(), move || {
                Ok(SystemOneCredentials {api_key:"synthetic-test-only".into(), base_url:endpoint.clone(), model:"elephant-1".into()})
            }))
        }
    }

    fn sentences(count: usize) -> Vec<Sentence> {
        (0..count).map(|i| Sentence {id:format!("s{i}"), text:format!("Synthetic experiment {i} describes an important method and its measured effect."), page:1, rects:vec![], page_width:600.0, page_height:800.0}).collect()
    }

    #[tokio::test]
    async fn sixteen_batches_are_serial_and_complete_in_order() {
        let api = MockApi::start(Duration::from_millis(20), "ok").await;
        let progress = Arc::new(Mutex::new(Vec::new()));
        let log = progress.clone();
        let result = score_sentence_batches(api.provider(), sentences(512), "Synthetic paper", &CancellationToken::new(), move |done,total| log.lock().unwrap().push((done,total))).await.unwrap();
        assert_eq!(api.calls.load(Ordering::SeqCst),16);
        assert_eq!(api.peak.load(Ordering::SeqCst),1);
        assert_eq!(result.len(),512);
        assert_eq!(result[0].0.id,"s0");
        assert_eq!(result[511].0.id,"s511");
        assert_eq!(*progress.lock().unwrap(),(1..=16).map(|n|(n,16)).collect::<Vec<_>>());
        for body in api.bodies.lock().unwrap().iter() {
            assert_eq!(body["state"]["sentences"].as_object().unwrap().len(),32);
            assert_eq!(body["questions"].as_object().unwrap().len(),160);
        }
    }

    #[tokio::test]
    async fn cancel_interrupts_active_request_and_never_starts_queued_batches() {
        let api = MockApi::start(Duration::from_secs(30), "ok").await;
        let token = CancellationToken::new();
        let task_token = token.clone();
        let provider = api.provider();
        let task = tokio::spawn(async move { score_sentence_batches(provider, sentences(512), "Synthetic paper", &task_token, |_,_| panic!("cancelled batch must not complete")).await });
        tokio::time::timeout(Duration::from_secs(3), async {
            while api.calls.load(Ordering::SeqCst)==0 { tokio::time::sleep(Duration::from_millis(10)).await; }
        }).await.unwrap();
        token.cancel();
        assert!(tokio::time::timeout(Duration::from_secs(1),task).await.unwrap().unwrap().is_err());
        tokio::time::timeout(Duration::from_secs(1), async {
            while api.active.load(Ordering::SeqCst)!=0 { tokio::time::sleep(Duration::from_millis(10)).await; }
        }).await.unwrap();
        assert_eq!(api.calls.load(Ordering::SeqCst),1);
    }

    #[tokio::test]
    async fn independent_paper_jobs_share_one_global_request_slot() {
        let api = MockApi::start(Duration::from_millis(50),"ok").await;
        let mut jobs=Vec::new();
        for _ in 0..4 {
            let provider=api.provider();
            jobs.push(tokio::spawn(async move {
                score_sentence_batches(provider,sentences(32),"Synthetic paper",&CancellationToken::new(),|_,_|{}).await
            }));
        }
        for job in jobs {assert_eq!(job.await.unwrap().unwrap().len(),32);}
        assert_eq!(api.calls.load(Ordering::SeqCst),4);
        assert_eq!(api.peak.load(Ordering::SeqCst),1);
    }

    #[tokio::test]
    async fn cancellation_while_queued_sends_no_request() {
        let api = MockApi::start(Duration::from_secs(30),"ok").await;
        let first_token=CancellationToken::new();
        let first_cancel=first_token.clone();
        let provider=api.provider();
        let first=tokio::spawn(async move {score_sentence_batches(provider,sentences(32),"Synthetic paper",&first_cancel,|_,_|{}).await});
        tokio::time::timeout(Duration::from_secs(3),async {
            while api.calls.load(Ordering::SeqCst)==0 {tokio::time::sleep(Duration::from_millis(10)).await;}
        }).await.unwrap();
        let second_token=CancellationToken::new();
        let second_cancel=second_token.clone();
        let provider=api.provider();
        let second=tokio::spawn(async move {score_sentence_batches(provider,sentences(32),"Synthetic paper",&second_cancel,|_,_|{}).await});
        tokio::time::sleep(Duration::from_millis(30)).await;
        second_token.cancel();
        assert!(tokio::time::timeout(Duration::from_secs(1),second).await.unwrap().unwrap().is_err());
        assert_eq!(api.calls.load(Ordering::SeqCst),1);
        first_token.cancel();
        assert!(first.await.unwrap().is_err());
    }

    #[tokio::test]
    async fn pre_cancelled_job_sends_nothing() {
        let api = MockApi::start(Duration::ZERO, "ok").await;
        let token = CancellationToken::new(); token.cancel();
        assert!(score_sentence_batches(api.provider(),sentences(32),"Synthetic paper",&token,|_,_| panic!("cancelled job")).await.is_err());
        assert_eq!(api.calls.load(Ordering::SeqCst),0);
    }

    #[tokio::test]
    async fn invalid_or_error_response_does_not_report_completion() {
        for mode in ["missing","error"] {
            let api = MockApi::start(Duration::ZERO,mode).await;
            assert!(score_sentence_batches(api.provider(),sentences(64),"Synthetic paper",&CancellationToken::new(),|_,_| panic!("failed batch must not complete")).await.is_err());
            assert_eq!(api.calls.load(Ordering::SeqCst),1);
        }
    }
}
