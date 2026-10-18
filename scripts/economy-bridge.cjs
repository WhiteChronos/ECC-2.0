'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');

function run(argv) {
  const allowed = new Set(['--tasks','--token-economy-root','--allow-local-inference','--output']);
  const options = {};
  for(let i=0;i<argv.length;i++) {
    const key=argv[i];
    if(!allowed.has(key) || Object.hasOwn(options,key)) throw new Error('Argumentos invalidos.');
    if(key==='--allow-local-inference') options[key]=true;
    else { if(!argv[i+1] || argv[i+1].startsWith('--')) throw new Error('Valor ausente.'); options[key]=argv[++i]; }
  }
  const root=options['--token-economy-root'];
  if(!root) throw new Error('Informe --token-economy-root; ECC independente continua disponivel.');
  const python=path.join(root,'.venv','Scripts','python.exe');
  if(!fs.existsSync(python) || !fs.existsSync(path.join(root,'src','token_economy','cli.py'))) throw new Error('Parceiro Token-Economy ausente; nenhum modelo iniciado.');
  const args=['-m','token_economy','integration-smoke','--ecc-root',path.resolve(__dirname,'..')];
  if(options['--tasks']) args.push('--tasks',options['--tasks']);
  if(options['--output']) args.push('--output',options['--output']);
  if(options['--allow-local-inference']) args.push('--allow-local-inference');
  const result=spawnSync(python,args,{cwd:root,env:{...process.env,PYTHONPATH:path.join(root,'src')},shell:false,windowsHide:true,stdio:'inherit'});
  return result.status ?? 4;
}
module.exports={run};
if(require.main===module) {try {process.exitCode=run(process.argv.slice(2));} catch(error) {console.error(error.message);process.exitCode=3;}}
