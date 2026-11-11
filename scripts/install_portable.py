"""Verify and extract one cloud-built app archive; never retrieve model outputs."""
import argparse
import hashlib
import json
import os
import subprocess
import zipfile
from pathlib import Path, PurePosixPath


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    args=parser.parse_args()
    workspace=args.workspace.resolve()
    downloads=workspace/'AgenteroKaggleAdapter/.work/download'
    downloads.mkdir(parents=True,exist_ok=True)
    for name in ('Agentero-Kaggle-v1-windows-x64.zip','SHA256SUMS.txt','BUILD-MANIFEST.json'):
        subprocess.run(['gh','release','download','adapter-v1','--repo','yatools/agentero-kaggle-adapter','--pattern',name,'--dir',str(downloads),'--clobber'],check=True)
    archive=downloads/'Agentero-Kaggle-v1-windows-x64.zip'
    expected=(downloads/'SHA256SUMS.txt').read_text(encoding='utf-8').split()[0]
    actual=hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual!=expected:raise RuntimeError('Application archive checksum mismatch')
    target=(workspace/'Agentero-Kaggle'/('build-'+actual[:12])).resolve()
    if not target.is_relative_to(workspace):raise RuntimeError('App directory escapes the deployment workspace')
    target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        for item in handle.infolist():
            parts=PurePosixPath(item.filename).parts
            if not parts or parts[0]!='Agentero-Kaggle-v1' or '\\' in item.filename or '..' in parts:
                raise RuntimeError('Unexpected archive path')
            if len(parts)==1:continue
            if any(':' in part for part in parts):raise RuntimeError('Invalid Windows archive path')
            path=target.joinpath(*parts[1:]).resolve()
            if not path.is_relative_to(target):raise RuntimeError('Archive escapes app directory')
            if path.suffix.lower() in ('.gguf','.safetensors','.pth','.pt'):
                raise RuntimeError('Model weights must never be included')
            if item.is_dir():path.mkdir(parents=True,exist_ok=True)
            else:
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(handle.read(item))
    manifest=json.loads((target/'BUILD-MANIFEST.json').read_text(encoding='utf-8'))
    if manifest['upstream_commit']!='fdacc2bc9da8a4e5569cf986acf2ef09e62d396b':
        raise RuntimeError('Unexpected application source revision')
    patch=workspace/'AgenteroKaggleAdapter/patches/agentero.patch'
    if manifest['patch_sha256']!=hashlib.sha256(patch.read_bytes()).hexdigest():
        raise RuntimeError('Archive does not match the current verified adaptation patch')
    if manifest['profile']!={'batch_size':32,'highlight_concurrency':1,'request_timeout_seconds':300}:
        raise RuntimeError('Unexpected decision runtime profile')
    if manifest.get('model_weights_included') is not False:
        raise RuntimeError('Archive must be explicitly model-free')
    for name,digest in manifest['files'].items():
        path=(target/name).resolve()
        if not path.is_relative_to(target) or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Portable resource verification failed')
    executable=target/'agentero.exe'
    state={'executable':str(executable),'executable_sha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
           'archive_size_bytes':archive.stat().st_size,'archive_sha256':actual,'upstream_commit':manifest['upstream_commit'],
           'profile':manifest['profile'],'local_model_download_bytes':0}
    (workspace/'deployment/portable-install.json').write_text(json.dumps(state,indent=2),encoding='utf-8')
    print(json.dumps(state,indent=2))


if __name__=='__main__':main()
