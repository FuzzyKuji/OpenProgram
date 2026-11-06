import assert from "node:assert/strict";
import test from "node:test";
import { installLoader, STUBS } from "../_support/load.mjs";
import { installDom, render } from "../_support/dom.mjs";

installLoader({
  stubs: {
    "@tanstack/react-query": "export const useQueryClient=()=>({invalidateQueries(){}});",
    "@/lib/i18n": STUBS.i18n,
    "@/lib/prefs/settings-cache": "export const readCachedSettings=()=>globalThis.cachedProviders;export const cachedFetch=()=>globalThis.loadProviders();export const invalidate=()=>{};",
    "@/lib/nav/shallow-nav": "export const pushPath=()=>{};",
    "@/components/ui/search-input": "export const SearchInput=()=>null;",
    "./detail": "export const Detail=({provider})=>globalThis.providerElement('output',{},provider.id);",
    "./provider-item": "export const ProviderItem=()=>null;",
    "./routing-overview": "export const RoutingOverview=()=>null;",
    "./add-custom-provider": "export const AddCustomProvider=()=>null;",
    "./types": "export const refreshAgentChip=()=>{};",
    "./auth/api-key": "export const ApiKey=()=>null;",
  },
});
installDom();
const { act, createElement } = await import("react");
globalThis.providerElement = createElement;
const {ProvidersSection}=await import('../../components/settings/providers/index.tsx');
test('URL provider wins over an earlier pending default selection without reloading list',async()=>{
 let resolveList,calls=0;
 const promise=new Promise(resolve=>resolveList=resolve);
 globalThis.loadProviders=()=>{calls++;return promise;};
 const view=await render(createElement(ProvidersSection));
 await view.rerender(createElement(ProvidersSection,{initialProviderId:'ollama'}));
 await act(async()=>resolveList({providers:[{id:'default',label:'Default',enabled:true},{id:'ollama',label:'Ollama',enabled:false}]}));
 assert.equal(view.container.querySelector('output').textContent,'ollama');
 assert.equal(calls,1);
 await view.unmount();
});

test('a fresh cached catalog is visible on the first render before effects',async()=>{
 const {renderToStaticMarkup}=await import('react-dom/server');
 globalThis.cachedProviders={providers:[{id:'ollama',label:'Ollama',enabled:true}]};
 // The section opens on the Overview; a route to one provider shows that provider from the cache alone.
 assert.match(renderToStaticMarkup(createElement(ProvidersSection,{initialProviderId:'ollama'})),/<output>ollama<\/output>/);
 globalThis.cachedProviders=undefined;
});
