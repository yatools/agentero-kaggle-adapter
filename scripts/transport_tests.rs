
#[cfg(test)]
mod kaggle_transport_tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    async fn api(chunked: bool) -> (String, std::sync::Arc<tokio::sync::Notify>, tokio::sync::mpsc::UnboundedSender<bool>, tokio::task::JoinHandle<()>) {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let url = format!("http://{}/v1/systemone",listener.local_addr().unwrap());
        let ready = std::sync::Arc::new(tokio::sync::Notify::new());
        let signal = ready.clone();
        let (tx,mut rx) = tokio::sync::mpsc::unbounded_channel::<bool>();
        let task = tokio::spawn(async move {
            let (mut socket,_) = listener.accept().await.unwrap();
            let mut raw=Vec::new();
            loop {
                let mut buf=[0;4096]; let n=socket.read(&mut buf).await.unwrap();
                if n==0 {return;}
                raw.extend_from_slice(&buf[..n]);
                if let Some(end)=raw.windows(4).position(|x| x==b"\r\n\r\n") {
                    let headers=String::from_utf8_lossy(&raw[..end]).to_lowercase();
                    let size:usize=headers.lines().find_map(|l|l.strip_prefix("content-length:")).unwrap().trim().parse().unwrap();
                    if raw.len()>=end+4+size {break;}
                }
            }
            if chunked {
                socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n").await.unwrap();
            }
            signal.notify_one();
            while let Some(finish)=rx.recv().await {
                if finish {
                    let body=r#"{"answers":{"q":{"score":2.0}}}"#;
                    let response=format!("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body);
                    let _=socket.write_all(response.as_bytes()).await;break;
                }
                if socket.write_all(b"1\r\n \r\n").await.is_err() {break;}
            }
        });
        (url,ready,tx,task)
    }

    async fn settle() {
        for _ in 0..100 {tokio::task::yield_now().await;}
    }

    async fn real_deadline() {
        let start=std::time::Instant::now();
        while start.elapsed()<Duration::from_secs(10) {tokio::task::yield_now().await;}
    }

    async fn wait_ready(ready: &tokio::sync::Notify) {
        tokio::select! {
            _=ready.notified()=>{},
            _=real_deadline()=>panic!("mock HTTP server did not receive the request"),
        }
    }

    async fn finish<T>(mut task: tokio::task::JoinHandle<T>) -> T {
        tokio::select! {
            result=&mut task=>result.unwrap(),
            _=real_deadline()=>{task.abort();panic!("mock HTTP response did not complete");},
        }
    }

    fn provider(url: String) -> SystemOneProvider {
        SystemOneProvider::with_shared_client(move || Ok(SystemOneCredentials {
            api_key:"synthetic-test-only".into(),base_url:url.clone(),model:"elephant-1".into()
        }))
    }

    #[tokio::test(start_paused = true)]
    async fn response_can_outlive_the_original_120_second_deadline() {
        // Keep the runtime runnable so virtual time advances only when requested.
        let driver=tokio::spawn(async {loop {tokio::task::yield_now().await;}});
        let (url,ready,tx,server)=api(false).await;
        let request=tokio::spawn(async move {provider(url).complete(json!({"state":"test","questions":{}})).await});
        wait_ready(&ready).await;
        tokio::time::advance(Duration::from_secs(150)).await;settle().await;
        assert!(!request.is_finished(),"the old 120 second timeout must not fire");
        tx.send(true).unwrap();
        assert!(finish(request).await.is_ok());
        server.await.unwrap();driver.abort();
    }

    #[tokio::test(start_paused = true)]
    async fn whitespace_does_not_extend_the_300_second_total_deadline() {
        let driver=tokio::spawn(async {loop {tokio::task::yield_now().await;}});
        let (url,ready,tx,server)=api(true).await;
        let request=tokio::spawn(async move {provider(url).complete(json!({"state":"test","questions":{}})).await});
        wait_ready(&ready).await;settle().await;
        for _ in 0..4 {
            tx.send(false).unwrap();settle().await;
            tokio::time::advance(Duration::from_secs(60)).await;settle().await;
            assert!(!request.is_finished());
        }
        tx.send(false).unwrap();settle().await;
        tokio::time::advance(Duration::from_secs(61)).await;settle().await;
        assert!(request.is_finished(),"the request must have a bounded total lifetime");
        assert!(finish(request).await.is_err());
        server.abort();driver.abort();
    }
}
