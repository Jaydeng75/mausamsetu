import {spawn} from 'node:child_process';
import {cp,access,mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {parseArgs} from 'node:util';
import path from 'node:path';

const root=fileURLToPath(new URL('../',import.meta.url));
const {values}=parseArgs({options:{hostname:{type:'string'},port:{type:'string'}}});
const port=Number(values.port??process.env.PORT??3000);
if(!Number.isInteger(port)||port<1||port>65535)throw Error('Invalid server port');
const standalone=path.join(root,'.next','standalone');
const server=path.join(standalone,'server.js');
await access(server).catch(()=>{throw Error('Build the standalone application with npm run build first.');});
await mkdir(path.join(standalone,'.next'),{recursive:true});
await cp(path.join(root,'.next','static'),path.join(standalone,'.next','static'),{recursive:true});
await cp(path.join(root,'public'),path.join(standalone,'public'),{recursive:true});
const child=spawn(process.execPath,[server],{
 cwd:standalone,stdio:'inherit',
 env:{...process.env,NODE_ENV:'production',HOSTNAME:values.hostname??'127.0.0.1',PORT:String(port)},
});
for(const signal of ['SIGINT','SIGTERM'])process.on(signal,()=>child.kill(signal));
child.on('error',error=>{console.error(error.message);process.exitCode=1;});
child.on('exit',(code,signal)=>{process.exit(code??(signal?1:0));});
