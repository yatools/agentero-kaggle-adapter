"""Generate the reproducible patch from small, pinned source snapshots."""
import difflib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / '.work/original'
paths = {
    'service.rs':'src-tauri/src/features/jev/service.rs',
    'system_one.rs':'crates/agentero-core/src/decision/providers/system_one.rs',
    'updater.rs':'src-tauri/src/features/system/updater.rs',
    'core-Cargo.toml':'crates/agentero-core/Cargo.toml',
}
diffs=[]
for name,path in paths.items():
    old=(ORIGINAL/name).read_text(encoding='utf-8')
    new=old
    if name=='service.rs':
        new=new.replace('const JEV_CONCURRENCY: usize = 16;','const JEV_CONCURRENCY: usize = 1;')
        new=new.replace('let resp = provider.complete(request).await?;', '''let resp = tokio::select! {
                    biased;
                    _ = cancel_token.cancelled() => return Err(AppError::message("jEV smart highlight cancelled")),
                    result = provider.complete(request) => result?,
                };''')
        new=new.replace('.unwrap_or(0.0);', '''.filter(|value| value.is_finite() && (0.0..=3.0).contains(value))
                            .ok_or_else(|| AppError::message(format!("Invalid or missing decision score: {qid}")))?;''')
        start=new.index('    let total_batches = sentences.chunks(BATCH_SIZE).len();')
        end=new.index('    // Phase 2: build highlights',start)
        scoring=new[start:end]
        marker='    // Sort by batch index so output order is deterministic.'
        scoring=scoring[:scoring.index(marker)]+'''    let mut scored_batches = scored_batches;
    scored_batches.sort_by_key(|(idx, _)| *idx);
    Ok(scored_batches.into_iter().flat_map(|(_, decisions)| decisions).collect())
'''
        helper='''async fn score_sentence_batches<F: FnMut(usize, usize) + Send>(
    provider: Arc<SystemOneProvider>,
    sentences: Vec<Sentence>,
    title: &str,
    cancel_token: &CancellationToken,
    on_progress: F,
) -> Result<Vec<(Sentence, HighlightDecision)>, AppError> {
'''+scoring+'}\n\n'
        new=new[:start]+'''    let scored_sentences = score_sentence_batches(provider, sentences, title, cancel_token, on_progress).await?;

'''+new[end:]
        position=new.index('async fn jev_suggest_highlights_impl')
        new=new[:position]+helper+new[position:]
        new+='\n'+(ROOT/'scripts/service_tests.rs').read_text(encoding='utf-8')
    elif name=='system_one.rs':
        new=new.replace('Duration::from_secs(120)','Duration::from_secs(300)')
        new=new.replace('unwrap_or_else(|_| reqwest::Client::new())', 'unwrap_or_else(|_| reqwest::Client::builder().timeout(Duration::from_secs(300)).build().expect("Could not initialize decision HTTP client"))')
        new+='\n'+(ROOT/'scripts/transport_tests.rs').read_text(encoding='utf-8')
    elif name=='core-Cargo.toml':
        new=new.replace('features = ["macros", "rt", "fs"]','features = ["macros", "rt", "fs", "test-util", "net"]')
    else:
        start=new.index('    let mut builder = webview.updater_builder()')
        new=new[:start]+'''    // This portable build is updated from its reproducible adapter repository.
    let _ = (webview, proxy, retry_on_timeout);
    Ok(None)
}
'''
        new=new.replace('use tauri_plugin_updater::{Error, UpdaterExt};\n','').replace('use tauri::{Manager, ResourceId, Runtime, Webview};','use tauri::{ResourceId, Runtime, Webview};').replace('use std::time::Duration;\n','').replace('const CHECK_TIMEOUT: Duration = Duration::from_secs(30);\n','')
    assert new!=old,name
    patched=ROOT/'.work/patched'/name;patched.parent.mkdir(parents=True,exist_ok=True);patched.write_text(new,encoding='utf-8',newline='\n')
    diffs.extend(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+path,tofile='b/'+path))
destination=ROOT/'patches/agentero.patch';destination.parent.mkdir(exist_ok=True)
destination.write_text(''.join(diffs),encoding='utf-8',newline='\n')
print('Generated pinned Agentero patch.')
