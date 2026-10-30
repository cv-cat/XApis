import * as glue from './node_modules/juicebox-sdk/juicebox-sdk_bg.js';
const bytes = await fetch(new URL('./juicebox-sdk_bg.wasm', import.meta.url)).then(r => {
  if (!r.ok) throw new Error('Cannot load key recovery engine');
  return r.arrayBuffer();
});
const {instance} = await WebAssembly.instantiate(bytes, {'./juicebox-sdk_bg.js': glue});
glue.__wbg_set_wasm(instance.exports);
export { Client, Configuration } from './node_modules/juicebox-sdk/juicebox-sdk_bg.js';
