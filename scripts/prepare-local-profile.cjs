'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {createHash, randomUUID} = require('node:crypto');

function digestFile(file) {
  const hash=createHash('sha256'),fd=fs.openSync(file,'r'),buffer=Buffer.alloc(4*1024*1024);
  try { let n; while((n=fs.readSync(fd,buffer,0,buffer.length,null))>0) hash.update(buffer.subarray(0,n)); }
  finally { fs.closeSync(fd); }
  return hash.digest('hex');
}

function prepareIsolatedBase(source, target) {
  const relative='manifests/registry.ollama.ai/library/qwen3/4b';
  const manifest=fs.readFileSync(path.join(source,relative));
  if(manifest.length>1024*1024)throw Error('Manifesto acima do limite.');
  const data=JSON.parse(manifest),layers=[data.config,...data.layers];
  let total=0;
  for(const layer of layers) {
    if(!/^sha256:[a-f0-9]{64}$/.test(layer.digest))throw Error('Digest invalido.');
    const name=layer.digest.replace(':','-'),from=path.join(source,'blobs',name),to=path.join(target,'blobs',name);
    const stat=fs.lstatSync(from);total+=stat.size;
    if(!stat.isFile()||stat.isSymbolicLink()||total>4*1024**3)throw Error('Camada invalida ou acima do limite.');
    fs.mkdirSync(path.dirname(to),{recursive:true});
    if(!fs.existsSync(to)) {
      const temporary=to+'.'+randomUUID()+'.tmp';
      fs.copyFileSync(from,temporary,fs.constants.COPYFILE_EXCL);
      if(digestFile(temporary)!==layer.digest.slice(7))throw Error('Copia com hash divergente; preservada para diagnostico.');
      fs.renameSync(temporary,to);
    } else if(digestFile(to)!==layer.digest.slice(7))throw Error('Camada existente divergiu; preservada.');
  }
  const destination=path.join(target,relative);fs.mkdirSync(path.dirname(destination),{recursive:true});
  if(fs.existsSync(destination)&&!fs.readFileSync(destination).equals(manifest))throw Error('Manifesto isolado divergiu; preservado.');
  if(!fs.existsSync(destination))fs.writeFileSync(destination,manifest,{flag:'wx'});
}
module.exports={prepareIsolatedBase};
