import {build} from 'esbuild';
import {mkdir,copyFile,readFile,writeFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
const out=path.resolve(root,'../console/static/vendor');
await mkdir(out,{recursive:true});
await build({absWorkingDir:root,entryPoints:['entry.mjs'],outfile:path.join(out,'chat-sdk.mjs'),bundle:true,format:'esm',platform:'browser',target:'es2022',minify:true,
  external:['crypto','fs','url','module'],
  plugins:[{name:'juicebox-browser-loader',setup(b){b.onResolve({filter:/^juicebox-sdk$/},()=>({path:path.join(root,'juicebox-browser.mjs')}));}}]});
await copyFile(path.join(root,'node_modules/@xdevplatform/chat-xdk/pkg/chat_xdk_wasm_bg.wasm'),path.join(out,'chat_xdk_wasm_bg.wasm'));
await copyFile(path.join(root,'node_modules/juicebox-sdk/juicebox-sdk_bg.wasm'),path.join(out,'juicebox-sdk_bg.wasm'));
await writeFile(path.join(out,'NOTICE.txt'),await readFile(path.join(root,'node_modules/@xdevplatform/chat-xdk/LICENSE'),'utf8')+'\n\n'+await readFile(path.join(root,'node_modules/@xdevplatform/chat-xdk/THIRD_PARTY_NOTICES.md'),'utf8'));
