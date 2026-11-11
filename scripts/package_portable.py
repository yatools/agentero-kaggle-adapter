"""Package the Windows executable with the resources declared by upstream."""
import argparse
import hashlib
import json
import shutil
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path

UPSTREAM = 'fdacc2bc9da8a4e5569cf986acf2ef09e62d396b'
root = Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('source',type=Path)
args=parser.parse_args()
source=args.source.resolve()
metadata=json.loads(subprocess.check_output(['cargo','metadata','--no-deps','--format-version=1'],cwd=source,text=True))
release=Path(metadata['target_directory'])/'release'
output=root/'output';output.mkdir(exist_ok=True)
portable=output/'Agentero-Kaggle-v1';portable.mkdir(exist_ok=True)
shutil.copy2(release/'agentero.exe',portable/'agentero.exe')
for dll in release.glob('*.dll'):shutil.copy2(dll,portable/dll.name)
for name in ('pdfium','adapters','rtex/tex'):
    folder=source/'src-tauri'/name
    if not folder.is_dir():raise RuntimeError('Missing required resource: '+name)
    shutil.copytree(folder,portable/name,dirs_exist_ok=True)
workers=list((source/'src-tauri/binaries').glob('agentero-plugin-host-*-pc-windows-msvc.exe'))
if len(workers)!=1:raise RuntimeError('Expected exactly one Windows plugin sidecar')
shutil.copy2(workers[0],portable/'agentero-plugin-host.exe')
for name in ('LICENSE','LICENSE.md','LICENSE-MIT','NOTICE','.github/THIRD_PARTY_NOTICES.md'):
    path=source/name
    if path.is_file():shutil.copy2(path,portable/path.name)
manifest={'upstream_commit':UPSTREAM,'patch_sha256':hashlib.sha256((root/'patches/agentero.patch').read_bytes()).hexdigest(),'build_utc':datetime.now(timezone.utc).isoformat(),'rustc':subprocess.check_output(['rustc','--version'],text=True).strip(),'node':subprocess.check_output(['node','--version'],text=True).strip(),'profile':{'batch_size':32,'highlight_concurrency':1,'request_timeout_seconds':300},'model_weights_included':False,'files':{}}
for path in sorted(portable.rglob('*')):
    if path.is_file():
        if path.suffix.lower() in ('.gguf','.safetensors'):raise RuntimeError('Weights must never be packaged')
        manifest['files'][path.relative_to(portable).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
(portable/'BUILD-MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
shutil.copy2(root/'README.md',portable/'README.md')
archive=output/'Agentero-Kaggle-v1-windows-x64.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as handle:
    for path in sorted(portable.rglob('*')):
        if path.is_file():handle.write(path,path.relative_to(output))
checksum=hashlib.sha256(archive.read_bytes()).hexdigest()
(output/'SHA256SUMS.txt').write_text(checksum+'  '+archive.name+'\n',encoding='ascii')
(output/'BUILD-MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print(json.dumps({'archive':archive.name,'size_bytes':archive.stat().st_size,'sha256':checksum}))
